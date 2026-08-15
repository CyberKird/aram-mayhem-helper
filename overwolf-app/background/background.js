/* Ascultatorul de evenimente de joc (GEP) si sursa de adevar pentru overlay.
 *
 * Nu deseneaza nimic; aduna starea si o trimite ferestrei de overlay.
 */

(function () {
  "use strict";

  var L = window.MayhemLogic;
  var B = window.MayhemBuild;

  var FEATURES = ["me", "game_info", "match_info", "live_client_data"];
  var MAYHEM_HINTS = ["mayhem", "kiwi"];   // KIWI e numele intern al modului

  var data = {};          // fisierele statice din data/
  var state = {
    roster: { allies: [], enemies: [], localChampion: null },
    augments: [],
    picked: null,
    build: null,
    highlights: [],
    status: "asteapta jocul"
  };
  var raw = { arenaTeams: null, allPlayers: null, gameMode: null };
  var pending = {};       // scrape-uri in curs, ca sa nu pornim doua deodata

  /* --- fisiere statice ------------------------------------------------ */

  function loadJson(path) {
    return fetch(path).then(function (r) { return r.json(); });
  }

  function loadStaticData() {
    return Promise.all([
      loadJson("../data/augments-global.json"),
      loadJson("../data/augment-map.json"),
      loadJson("../data/champion-tags.json"),
      loadJson("../data/item-sprites.json"),
      loadJson("../rules/item-rules.json")
    ]).then(function (r) {
      data.globalAugments = r[0];
      data.augmentMap = r[1];
      data.championTags = r[2];
      data.itemSprites = r[3];
      data.rules = r[4];
    });
  }

  /* Build-ul si augmentele pe campion se aduc la prima intalnire a
   * campionului si raman in localStorage. Nu pre-descarcam toti campionii. */
  function cached(key) {
    try {
      var hit = localStorage.getItem(key);
      return hit ? JSON.parse(hit) : null;
    } catch (e) { return null; }
  }

  function cache(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch (e) { /* plin */ }
  }

  /* --- overlay --------------------------------------------------------- */

  function push() {
    overwolf.windows.sendMessage("overlay", "state", state, function () {});
  }

  function setStatus(text) {
    state.status = text;
    push();
  }

  function showOverlay(show) {
    overwolf.windows.obtainDeclaredWindow("overlay", function (res) {
      if (!res || !res.success) return;
      var id = res.window.id;
      if (show) overwolf.windows.restore(id, function () {});
      else overwolf.windows.hide(id, function () {});
    });
  }

  /* --- scraping lenes -------------------------------------------------- */

  /* Deschide pagina u.gg intr-o fereastra ascunsa si ruleaza extractorul.
   * u.gg e o aplicatie React, deci fara un browser real nu se poate citi. */
  function scrapeBuild(champion, done) {
    var key = "build:" + champion;
    var hit = cached(key);
    if (hit) return done(hit);
    if (pending[key]) return;
    pending[key] = true;

    overwolf.windows.obtainDeclaredWindow("scraper", function (res) {
      if (!res || !res.success) { pending[key] = false; return done(null); }
      var id = res.window.id;
      var url = B.buildUrl(champion);
      var source = B.extractBuildSource(B.SECTIONS);

      overwolf.windows.executeJavascript(id, "location.href=" + JSON.stringify(url),
        function () {
          // u.gg randeaza clientside; ii lasam timp sa deseneze itemii
          setTimeout(function () {
            overwolf.windows.executeJavascript(id, source, function (out) {
              pending[key] = false;
              var parsed = null;
              try { parsed = JSON.parse(out && out.result ? out.result : out); }
              catch (e) { parsed = null; }
              if (!parsed) return done(null);
              var build = B.resolveBuild(parsed, data.itemSprites);
              build.champion = champion;
              cache(key, build);
              done(build);
            });
          }, 6000);
        });
    });
  }

  /* --- reactii la evenimente ------------------------------------------- */

  function isMayhem() {
    var mode = String(raw.gameMode || "").toLowerCase();
    return MAYHEM_HINTS.some(function (h) { return mode.indexOf(h) !== -1; });
  }

  function refreshRoster() {
    var roster = L.parseRoster(raw.arenaTeams, raw.allPlayers);
    var changedChampion = roster.localChampion !== state.roster.localChampion;
    state.roster = roster;

    if (roster.localChampion && changedChampion) {
      state.build = null;
      state.highlights = [];
      setStatus("aduc build-ul pentru " + roster.localChampion + "...");
      scrapeBuild(roster.localChampion, function (build) {
        state.build = build;
        state.status = build ? "" : "build indisponibil";
        recomputeHighlights();
        push();
      });
    }
    recomputeHighlights();
    push();
  }

  function recomputeHighlights() {
    if (!state.build || !state.build.pool) { state.highlights = []; return; }
    state.highlights = L.evaluateRules(state.roster, data.championTags,
                                       data.rules, state.build.pool);
  }

  function refreshAugments(rawAugments) {
    var offers = L.parseAugmentOffers(rawAugments);
    if (!offers.length) { state.augments = []; push(); return; }

    var champ = state.roster.localChampion;
    var champAugments = champ ? cached("augments:" + champ) : null;
    state.augments = L.rateOffers(offers, data.augmentMap, champAugments,
                                  data.globalAugments);
    push();
  }

  var loggedFirstInfo = false;

  function onInfo(info) {
    if (!info) return;
    if (!loggedFirstInfo) {
      loggedFirstInfo = true;
      console.log("[aram-mayhem] primul payload GEP primit:", info);
    }
    var me = info.me || {};
    var gameInfo = info.game_info || {};
    var live = info.live_client_data || {};

    if (gameInfo.arena_teams !== undefined) { raw.arenaTeams = gameInfo.arena_teams; refreshRoster(); }
    if (live.all_players !== undefined) { raw.allPlayers = live.all_players; refreshRoster(); }
    if (gameInfo.game_mode !== undefined) raw.gameMode = gameInfo.game_mode;
    if (info.match_info && info.match_info.game_mode !== undefined) {
      raw.gameMode = info.match_info.game_mode;
    }

    if (me.augments !== undefined) refreshAugments(me.augments);
    if (me.picked_augment !== undefined) {
      state.picked = me.picked_augment;
      state.augments = [];      // s-a ales, ascundem panoul de oferte
      push();
    }
  }

  /* --- pornire --------------------------------------------------------- */

  function subscribe() {
    overwolf.games.events.setRequiredFeatures(FEATURES, function (res) {
      if (!res || !res.success) {
        console.warn("[aram-mayhem] setRequiredFeatures a esuat, reincerc in 3s:", res);
        // GEP nu e gata imediat dupa ce porneste jocul; reincercam
        setTimeout(subscribe, 3000);
        return;
      }
      console.log("[aram-mayhem] GEP abonat cu succes la:", res.supportedFeatures || FEATURES);
      overwolf.games.events.getInfo(function (info) {
        console.log("[aram-mayhem] getInfo initial:", info);
        if (info && info.success) onInfo(info.res || info.info);
      });
    });
  }

  function onGameRunning(running) {
    console.log("[aram-mayhem] onGameRunning:", running);
    showOverlay(running);
    if (running) subscribe();
    else {
      state.augments = [];
      state.roster = { allies: [], enemies: [], localChampion: null };
      setStatus("asteapta jocul");
    }
  }

  function isLeague(info) {
    return info && info.isRunning &&
           Math.floor(info.id / 10) === 5426;
  }

  function start() {
    overwolf.games.events.onInfoUpdates2.addListener(function (e) {
      onInfo(e && e.info);
    });

    overwolf.games.onGameInfoUpdated.addListener(function (e) {
      if (e && e.gameInfo) onGameRunning(isLeague(e.gameInfo));
    });
    overwolf.games.getRunningGameInfo(function (info) {
      onGameRunning(isLeague(info));
    });
  }

  loadStaticData().then(start, function (e) {
    setStatus("nu am putut incarca datele: " + e);
  });
})();
