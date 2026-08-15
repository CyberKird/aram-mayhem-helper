/* Deseneaza starea primita de la background. Nu ia nicio decizie singur.
 *
 * Cu ?mock=1 se randeaza cu date fixe, ca sa se poata verifica aspectul
 * intr-un browser obisnuit, fara Overwolf si fara joc pornit.
 */

(function () {
  "use strict";

  var TIER_CLASS = {
    "S+": "sp", "S": "s", "A": "a", "B": "b", "C": "c", "D": "d"
  };

  var BUILD_LABELS = {
    starting: "START",
    core: "CORE",
    fourth: "ITEM 4",
    fifth: "ITEM 5",
    sixth: "ITEM 6"
  };

  var main = document.getElementById("main");
  var champLabel = document.getElementById("champ");

  function suffix(tier) {
    return TIER_CLASS[tier] || "x";
  }

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function label(text) {
    return el("div", "section-label", text);
  }

  function augmentRow(entry) {
    var row = el("div", "row" + (entry.isBest ? " best c-" + suffix(entry.tier) : ""));
    row.appendChild(el("span", "badge t-" + suffix(entry.tier), entry.tier));
    row.appendChild(el("span", "name", entry.name));
    if (entry.isBest) {
      row.appendChild(el("span", "tag c-" + suffix(entry.tier), "BEST"));
    } else if (entry.source === "champion") {
      row.appendChild(el("span", "why", "pe campion"));
    }
    return row;
  }

  function buildBlock(name, items, hot) {
    var block = el("div", "build-block");
    block.appendChild(label(BUILD_LABELS[name] || name.toUpperCase()));
    var list = el("div", "items");
    items.forEach(function (item) {
      var hit = hot[item];
      var node = el("span", "item" + (hit ? " hot" : ""), item);
      if (hit) node.title = hit;
      list.appendChild(node);
    });
    block.appendChild(list);
    return block;
  }

  function render(state) {
    main.innerHTML = "";
    champLabel.textContent = (state.roster && state.roster.localChampion) || "";

    if (state.augments && state.augments.length) {
      var box = el("div");
      box.appendChild(label("AUGMENTE OFERITE"));
      state.augments.forEach(function (a) { box.appendChild(augmentRow(a)); });
      main.appendChild(box);
    }

    var hot = {};
    (state.highlights || []).forEach(function (h) { hot[h.item] = h.reason; });

    if (state.build) {
      var build = el("div");
      Object.keys(BUILD_LABELS).forEach(function (key) {
        var items = state.build[key];
        if (items && items.length) build.appendChild(buildBlock(key, items, hot));
      });
      main.appendChild(build);
    }

    if (state.highlights && state.highlights.length) {
      var why = el("div");
      why.appendChild(label("DE CE"));
      state.highlights.forEach(function (h) {
        var row = el("div", "row");
        row.appendChild(el("span", "name", h.item));
        row.appendChild(el("span", "why", h.reason));
        why.appendChild(row);
      });
      main.appendChild(why);
    }

    if (state.status) main.appendChild(el("div", "status", state.status));
  }

  /* --- date --------------------------------------------------------- */

  var MOCK = {
    roster: {
      localChampion: "Sett",
      allies: ["Sett", "Lux", "Thresh", "Jinx", "Garen"],
      enemies: ["Ahri", "Veigar", "Syndra", "Lulu", "Soraka"]
    },
    augments: [
      { name: "Goliath", tier: "S+", isBest: true, source: "global" },
      { name: "Multishot", tier: "C", isBest: false, source: "global" },
      { name: "Overloaded", tier: "D", isBest: false, source: "champion" }
    ],
    build: {
      starting: ["Giant's Belt", "Ruby Crystal", "Health Potion"],
      core: ["Heartsteel", "Mercury's Treads", "Overlord's Bloodmail"],
      fourth: ["Warmog's Armor", "Sterak's Gage"],
      fifth: ["Sterak's Gage", "Warmog's Armor", "Force of Nature"],
      sixth: ["Sterak's Gage", "Spirit Visage", "Force of Nature"]
    },
    highlights: [
      { item: "Force of Nature", reason: "3+ inamici AP" },
      { item: "Spirit Visage", reason: "3+ inamici AP" },
      { item: "Mercury's Treads", reason: "3+ inamici AP" }
    ],
    status: ""
  };

  if (location.search.indexOf("mock=1") !== -1) {
    render(MOCK);
    return;
  }

  render({ status: "asteapta jocul" });

  if (typeof overwolf !== "undefined") {
    overwolf.windows.onMessageReceived.addListener(function (msg) {
      if (msg && msg.id === "state") render(msg.content);
    });
  }
})();
