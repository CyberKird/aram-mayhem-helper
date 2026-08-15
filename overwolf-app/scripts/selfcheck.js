/* Verifica logica pura a overlay-ului, fara Overwolf si fara League pornit.
 *
 *     node scripts/selfcheck.js
 */

const assert = require("assert");
const fs = require("fs");
const path = require("path");

const L = require("../lib/logic.js");

const root = path.join(__dirname, "..");
const read = (p) => JSON.parse(fs.readFileSync(path.join(root, p), "utf8"));

const globalAugments = read("data/augments-global.json");
const championTags = read("data/champion-tags.json");
const rules = read("rules/item-rules.json");

/* --- roster ---------------------------------------------------------- */

// forma 1: obiect cu echipe pe chei, ca string JSON (asa livreaza GEP)
const teamsAsString = JSON.stringify({
  team_1: [
    { champion: "Sett", is_local: true },
    { champion: "Lux" },
  ],
  team_2: [{ champion: "Ahri" }, { champion: "Garen" }],
});
let roster = L.parseRoster(teamsAsString, null);
assert.strictEqual(roster.localChampion, "Sett");
assert.deepStrictEqual(roster.allies, ["Sett", "Lux"]);
assert.deepStrictEqual(roster.enemies, ["Ahri", "Garen"]);

// forma 2: lista plata cu team id si championName
roster = L.parseRoster([
  { championName: "Jinx", team: "ORDER", isLocal: true },
  { championName: "Thresh", team: "ORDER" },
  { championName: "Zed", team: "CHAOS" },
], null);
assert.strictEqual(roster.localChampion, "Jinx");
assert.deepStrictEqual(roster.enemies, ["Zed"]);

// forma 3: arena_teams gol -> cade pe all_players
roster = L.parseRoster(null, [{ championName: "Ashe", team: "ORDER", isLocal: true }]);
assert.strictEqual(roster.source, "all_players");
assert.strictEqual(roster.localChampion, "Ashe");

// fara date: gol, nu exceptie
roster = L.parseRoster(null, null);
assert.deepStrictEqual(roster, { allies: [], enemies: [], localChampion: null, source: null });

// fara jucator local nu inventam echipe
roster = L.parseRoster([{ championName: "Ashe", team: "ORDER" }], null);
assert.strictEqual(roster.localChampion, null);
assert.deepStrictEqual(roster.allies, []);

/* --- augmente -------------------------------------------------------- */

const offers = L.parseAugmentOffers(JSON.stringify({
  augment_1: { name: "Goliath" },
  augment_2: { name: "Multishot" },
  augment_3: { name: "Overloaded" },
}));
assert.deepStrictEqual(offers, ["Goliath", "Multishot", "Overloaded"]);
assert.deepStrictEqual(L.parseAugmentOffers(null), []);
assert.deepStrictEqual(L.parseAugmentOffers("nu e json"), []);

// tier global pe raritate
assert.strictEqual(L.lookupTier("Goliath", "prismatic", null, globalAugments).tier, "S+");
assert.strictEqual(L.lookupTier("Heavy Hitter", "silver", null, globalAugments).tier, "S+");
assert.strictEqual(L.lookupTier("Tank Engine", "gold", null, globalAugments).tier, "S+");

// numele cu virgula nu trebuie sa se fi rupt la import
assert.strictEqual(L.lookupTier("Yowch, My Coins!", "gold", null, globalAugments).tier, "B");

// clasamentul specific campionului bate globalul
const champAugments = { augments: { Goliath: "C" } };
assert.deepStrictEqual(
  L.lookupTier("Goliath", "prismatic", champAugments, globalAugments),
  { tier: "C", source: "champion" }
);
// augment necunoscut nu arunca
assert.strictEqual(L.lookupTier("Nimic", "gold", null, globalAugments).tier, L.UNKNOWN);

// cel mai bun dintre cele oferite
const rated = offers.map((n) => L.lookupTier(n, "prismatic", null, globalAugments));
assert.strictEqual(L.bestIndex(rated), 0); // Goliath S+ vs Multishot C vs Overloaded D
assert.strictEqual(L.bestIndex([{ tier: "?" }, { tier: "D" }]), 1);
assert.strictEqual(L.bestIndex([{ tier: "S" }, { tier: "S" }]), 0); // egalitate -> primul

/* --- id intern -> nume afisat ---------------------------------------- */

const augmentMap = read("data/augment-map.json");

// forma pe care o are in datele de joc
assert.strictEqual(L.resolveAugment("ARAM_ADAPt", augmentMap).name, "ADAPt");
// fara prefix, daca GEP il trimite asa
assert.strictEqual(L.resolveAugment("ADAPt", augmentMap).name, "ADAPt");
// scriere diferita
assert.strictEqual(L.resolveAugment("aram_adapt", augmentMap).name, "ADAPt");
assert.strictEqual(L.resolveAugment("NuExista___", augmentMap), null);

// fiecare augment clasat pe u.gg trebuie sa fie recunoscut plecand de la
// id-ul intern, altfel nu-l putem evalua in joc
const ranked = [];
for (const [rarity, block] of Object.entries(globalAugments)) {
  if (typeof block !== "object" || Array.isArray(block)) continue;
  for (const names of Object.values(block)) ranked.push(...names);
}
const byName = new Map();
for (const [key, val] of Object.entries(augmentMap)) {
  if (!byName.has(val.name)) byName.set(val.name, key);
}
const unmapped = ranked.filter((n) => !byName.has(n));
assert.strictEqual(unmapped.length, 0, `augmente fara id intern: ${unmapped}`);

// lantul complet: id intern -> nume -> tier -> cel mai bun
const chain = L.rateOffers(
  [byName.get("Goliath"), byName.get("Multishot"), byName.get("Overloaded")],
  augmentMap, null, globalAugments
);
assert.deepStrictEqual(chain.map((c) => c.name), ["Goliath", "Multishot", "Overloaded"]);
assert.deepStrictEqual(chain.map((c) => c.tier), ["S+", "C", "D"]);
assert.ok(chain[0].isBest && !chain[1].isBest);

// un augment necunoscut ramane vizibil, marcat "?", nu dispare in tacere
const withUnknown = L.rateOffers(["ZzzNuExista", byName.get("Goliath")],
                                 augmentMap, null, globalAugments);
assert.strictEqual(withUnknown[0].tier, L.UNKNOWN);
assert.ok(withUnknown[1].isBest);

// raritatea din datele de joc trebuie sa se potriveasca cu cea de pe u.gg,
// altfel cautarea globala pe raritate cade
for (const [rarity, block] of Object.entries(globalAugments)) {
  if (typeof block !== "object" || Array.isArray(block)) continue;
  for (const names of Object.values(block)) {
    for (const n of names) {
      const meta = augmentMap[byName.get(n)];
      assert.strictEqual(meta.rarity, rarity, `raritate diferita pentru ${n}`);
    }
  }
}

/* --- motor de reguli ------------------------------------------------- */

const pool = ["Force of Nature", "Thornmail", "Rabadon's Deathcap", "Boots"];

// 3+ inamici AP -> evidentiaza MR-ul din pool
let hits = L.evaluateRules(
  { allies: [], enemies: ["Ahri", "Lux", "Veigar"] },
  championTags, rules, pool
);
assert.ok(hits.some((h) => h.item === "Force of Nature"), "asteptam MR la comp AP");

// invariantul critic: nu se sugereaza NIMIC din afara pool-ului campionului
const everyTeam = { allies: [], enemies: Object.keys(championTags).slice(0, 5) };
[pool, [], ["Boots"]].forEach((p) => {
  L.evaluateRules(everyTeam, championTags, rules, p).forEach((h) => {
    assert.ok(p.indexOf(h.item) !== -1, `item din afara pool-ului: ${h.item}`);
  });
});

// fara inamici nu se declanseaza nicio regula
assert.deepStrictEqual(L.evaluateRules({ allies: [], enemies: [] }, championTags, rules, pool), []);

// campioni necunoscuti in tags nu arunca si nu se numara
assert.deepStrictEqual(
  L.evaluateRules({ allies: [], enemies: ["Nimeni", "Altul", "X"] }, championTags, rules, pool),
  []
);

// fiecare categorie din reguli trebuie sa existe in tabela de categorii
rules.rules.forEach((r) => {
  assert.ok(rules.categories[r.suggestCategory], `categorie lipsa: ${r.suggestCategory}`);
});

const champCount = Object.keys(championTags).length;
console.log(`selfcheck OK (${champCount} campioni, ${rules.rules.length} reguli)`);
