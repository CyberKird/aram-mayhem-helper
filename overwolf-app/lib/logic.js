/* Logica pura a overlay-ului: roster, tier de augment, motor de reguli.
 *
 * Fara Overwolf, fara retea, fara DOM. Ruleaza si in Node (pentru selfcheck)
 * si in pagina overlay-ului.
 *
 * Toate formele de date de la GEP sunt tratate defensiv: documentatia Overwolf
 * nu fixeaza structura exacta pentru arena_teams si nu am putut-o verifica pe
 * un meci real, deci parserul accepta mai multe forme plauzibile.
 */

(function (root) {
  "use strict";

  var TIER_ORDER = ["S+", "S", "A", "B", "C", "D"];
  var UNKNOWN = "?";

  function tierRank(tier) {
    var i = TIER_ORDER.indexOf(tier);
    return i === -1 ? TIER_ORDER.length : i;
  }

  /* GEP trimite obiectele imbricate ca string, uneori url-encodat. */
  function decode(raw) {
    if (raw === null || raw === undefined) return null;
    if (typeof raw === "object") return raw;
    if (typeof raw !== "string") return null;
    var text = raw;
    try { text = decodeURIComponent(raw); } catch (e) { /* nu era encodat */ }
    try { return JSON.parse(text); } catch (e) { return null; }
  }

  function isTruthy(v) {
    return v === true || v === "true" || v === 1 || v === "1";
  }

  function championOf(player) {
    return player.champion || player.championName || player.champion_name ||
           player.rawChampionName || null;
  }

  /* Scoate lista plata de jucatori din oricare din formele plauzibile:
   * [{...}], {teams:[{players:[...]}]}, {team_1:[...], team_2:[...]} */
  function flattenPlayers(parsed) {
    if (!parsed) return [];
    if (Array.isArray(parsed)) {
      if (parsed.length && Array.isArray(parsed[0])) {
        return parsed.reduce(function (acc, group, i) {
          group.forEach(function (p) { acc.push(withTeam(p, i)); });
          return acc;
        }, []);
      }
      return parsed.slice();
    }
    if (Array.isArray(parsed.teams)) return flattenPlayers(parsed.teams.map(teamPlayers));
    var out = [];
    Object.keys(parsed).forEach(function (key) {
      var value = parsed[key];
      if (Array.isArray(value)) {
        value.forEach(function (p) { out.push(withTeam(p, key)); });
      } else if (value && typeof value === "object" && championOf(value)) {
        out.push(withTeam(value, value.team));
      }
    });
    return out;
  }

  function teamPlayers(team) {
    return Array.isArray(team) ? team : (team && team.players) || [];
  }

  function withTeam(player, team) {
    if (player && player.team === undefined && team !== undefined) {
      var copy = {};
      Object.keys(player).forEach(function (k) { copy[k] = player[k]; });
      copy.team = team;
      return copy;
    }
    return player;
  }

  /* {allies, enemies, localChampion} din arena_teams (+ all_players ca rezerva).
   * allies/enemies sunt liste de nume de campioni. */
  function parseRoster(arenaTeamsRaw, allPlayersRaw) {
    var players = flattenPlayers(decode(arenaTeamsRaw));
    var source = "arena_teams";

    if (!players.length) {
      players = flattenPlayers(decode(allPlayersRaw));
      source = "all_players";
    }
    if (!players.length) {
      return { allies: [], enemies: [], localChampion: null, source: null };
    }

    var local = null;
    players.forEach(function (p) {
      if (!local && (isTruthy(p.is_local) || isTruthy(p.isLocal) ||
                     isTruthy(p.isLocalPlayer))) local = p;
    });

    var allies = [], enemies = [];
    players.forEach(function (p) {
      var champ = championOf(p);
      if (!champ) return;
      // fara jucator local nu stim ce echipa e a noastra, deci totul e "inamic"
      // pana cand GEP ne spune: mai bine gol decat gresit
      var ally = local && String(p.team) === String(local.team);
      (ally ? allies : enemies).push(champ);
    });

    return {
      allies: allies,
      enemies: enemies,
      localChampion: local ? championOf(local) : null,
      source: source
    };
  }

  /* Cele 3-4 augmente oferite, ca lista de nume interne (apiName). */
  function parseAugmentOffers(augmentsRaw) {
    var parsed = decode(augmentsRaw);
    if (!parsed || typeof parsed !== "object") return [];
    return Object.keys(parsed)
      .filter(function (k) { return /^augment_\d+$/.test(k); })
      .sort()
      .map(function (k) {
        var v = parsed[k];
        return typeof v === "string" ? v : (v && v.name) || null;
      })
      .filter(Boolean);
  }

  function normalize(s) {
    return String(s).toLowerCase().replace(/[^a-z0-9]/g, "");
  }

  /* id intern de la GEP (ex. "ARAM_ADAPt") -> {name, rarity}.
   * Formatul exact trimis de GEP pentru Mayhem nu e documentat, deci incercam
   * si cu prefixul ARAM_, si o potrivire normalizata. */
  function resolveAugment(apiName, augmentMap) {
    if (!apiName || !augmentMap) return null;

    var direct = augmentMap[apiName] || augmentMap["ARAM_" + apiName];
    if (direct) return direct;

    var target = normalize(apiName);
    var keys = Object.keys(augmentMap);
    for (var i = 0; i < keys.length; i++) {
      var key = keys[i];
      if (normalize(key) === target || normalize(key) === "aram" + target) {
        return augmentMap[key];
      }
    }
    // ultima incercare: poate GEP trimite direct numele afisat
    for (var j = 0; j < keys.length; j++) {
      if (normalize(augmentMap[keys[j]].name) === target) return augmentMap[keys[j]];
    }
    return null;
  }

  /* Tier-ul unui augment: intai clasamentul specific campionului, apoi cel
   * global pe raritate. */
  function lookupTier(displayName, rarity, championAugments, globalAugments) {
    if (championAugments && championAugments.augments &&
        championAugments.augments[displayName]) {
      return { tier: championAugments.augments[displayName], source: "champion" };
    }
    var byRarity = globalAugments && globalAugments[String(rarity).toLowerCase()];
    if (byRarity) {
      var tiers = Object.keys(byRarity);
      for (var i = 0; i < tiers.length; i++) {
        if (byRarity[tiers[i]].indexOf(displayName) !== -1) {
          return { tier: tiers[i], source: "global" };
        }
      }
    }
    return { tier: UNKNOWN, source: null };
  }

  /* Indexul celui mai bun augment din lista de {tier}. La egalitate, primul. */
  function bestIndex(rated) {
    var best = -1, bestRank = null;
    rated.forEach(function (entry, i) {
      var rank = tierRank(entry.tier);
      if (bestRank === null || rank < bestRank) { best = i; bestRank = rank; }
    });
    return best;
  }

  /* Lantul complet pentru un set de oferte: id intern -> nume -> tier -> cel mai bun.
   * Augmentele nerecunoscute raman in lista, marcate "?", ca sa se vada in overlay
   * ca lipseste ceva, in loc sa dispara in tacere. */
  function rateOffers(apiNames, augmentMap, championAugments, globalAugments) {
    var rated = apiNames.map(function (apiName) {
      var meta = resolveAugment(apiName, augmentMap);
      if (!meta) return { apiName: apiName, name: apiName, rarity: null, tier: UNKNOWN, source: null };
      var t = lookupTier(meta.name, meta.rarity, championAugments, globalAugments);
      return { apiName: apiName, name: meta.name, rarity: meta.rarity,
               tier: t.tier, source: t.source };
    });
    var best = bestIndex(rated);
    rated.forEach(function (e, i) { e.isBest = (i === best); });
    return rated;
  }

  function matchesCondition(cond, roster, championTags) {
    var team = roster[cond.team] || [];
    var count = 0;
    team.forEach(function (champ) {
      var meta = championTags[champ];
      if (!meta) return;
      if (cond.damageType && meta.damageType !== cond.damageType) return;
      if (cond.tagIn) {
        var hit = (meta.tags || []).some(function (t) {
          return cond.tagIn.indexOf(t) !== -1;
        });
        if (!hit) return;
      }
      count++;
    });
    return count >= (cond.countGte || 1);
  }

  /* Itemii de evidentiat, cu motivul. Nu returneaza NICIODATA un item care nu e
   * deja in pool-ul campionului de pe u.gg: regulile filtreaza, nu inventeaza. */
  function evaluateRules(roster, championTags, ruleSet, itemPool) {
    var pool = itemPool || [];
    var out = [];
    var seen = {};

    (ruleSet.rules || []).forEach(function (rule) {
      if (!matchesCondition(rule.condition, roster, championTags)) return;
      var keywords = (ruleSet.categories || {})[rule.suggestCategory] || [];
      pool.forEach(function (item) {
        var hit = keywords.some(function (k) {
          return k.toLowerCase() === String(item).toLowerCase();
        });
        if (hit && !seen[item]) {
          seen[item] = true;
          out.push({ item: item, reason: rule.reason, rule: rule.id });
        }
      });
    });
    return out;
  }

  var api = {
    TIER_ORDER: TIER_ORDER,
    UNKNOWN: UNKNOWN,
    tierRank: tierRank,
    decode: decode,
    parseRoster: parseRoster,
    parseAugmentOffers: parseAugmentOffers,
    resolveAugment: resolveAugment,
    rateOffers: rateOffers,
    lookupTier: lookupTier,
    bestIndex: bestIndex,
    evaluateRules: evaluateRules
  };

  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.MayhemLogic = api;
})(typeof window !== "undefined" ? window : this);
