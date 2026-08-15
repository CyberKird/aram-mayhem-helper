/* Extrage build-ul de pe o pagina u.gg de ARAM.
 *
 * u.gg nu pune id-uri de itemi in DOM: deseneaza fiecare item dintr-un sprite
 * sheet, prin background-position. Coordonatele alea sunt exact cele publicate
 * de Data Dragon in item.json, deci maparea inversa (data/item-sprites.json)
 * e exacta.
 *
 * `extractBuildSource` se ruleaza IN pagina u.gg (fereastra ascunsa a
 * aplicatiei), `resolveBuild` traduce rezultatul in nume de itemi.
 */

(function (root) {
  "use strict";

  var SECTIONS = {
    starting: "Starting Items",
    core: "Core Items",
    fourth: "Fourth Item Options",
    fifth: "Fifth Item Options",
    sixth: "Sixth Item Options"
  };

  /* Codul asta ajunge ca string in pagina u.gg, deci nu poate folosi nimic
   * din afara lui. Intoarce {sectiune: ["item3|48,288", ...]}. */
  function extractBuildSource(sections) {
    return "(function(){var S=" + JSON.stringify(sections) + ";" + [
      "function parse(el){",
      "  var s=el.getAttribute('style')||'';",
      "  var sp=(s.match(/img\\/sprite\\/([a-z0-9]+)\\./i)||[])[1];",
      "  var p=s.match(/background-position:\\s*(-?\\d+)px\\s+(-?\\d+)px/);",
      "  return (sp&&p)?sp+'|'+Math.abs(+p[1])+','+Math.abs(+p[2]):null;",
      "}",
      "var out={};",
      "Object.keys(S).forEach(function(key){",
      "  var want=S[key];",
      "  var label=null, divs=document.querySelectorAll('div');",
      "  for(var i=0;i<divs.length;i++){",
      "    if(divs[i].textContent.trim()===want){label=divs[i];break;}",
      "  }",
      "  var list=label&&label.nextElementSibling;",
      "  if(!list){out[key]=[];return;}",
      "  var nodes=list.querySelectorAll('div[style*=\"background-image\"]');",
      "  var ids=[];",
      "  for(var j=0;j<nodes.length;j++){var c=parse(nodes[j]);if(c)ids.push(c);}",
      "  out[key]=ids;",
      "});",
      "return JSON.stringify(out);"
    ].join("") + "})()";
  }

  /* {sectiune: [coordonate]} -> {sectiune: [nume item], pool: [toti itemii]} */
  function resolveBuild(rawSections, spriteMap) {
    var build = {};
    var pool = [];
    var seen = {};

    Object.keys(rawSections || {}).forEach(function (key) {
      var names = [];
      (rawSections[key] || []).forEach(function (coord) {
        var parts = String(coord).split("|");
        var byCoord = spriteMap[parts[0]];
        var name = byCoord && byCoord[parts[1]];
        if (!name) return;
        names.push(name);
        if (!seen[name]) { seen[name] = true; pool.push(name); }
      });
      build[key] = names;
    });

    build.pool = pool;
    return build;
  }

  var api = {
    SECTIONS: SECTIONS,
    extractBuildSource: extractBuildSource,
    resolveBuild: resolveBuild,
    buildUrl: function (champion) {
      var slug = String(champion).toLowerCase().replace(/[^a-z0-9]/g, "");
      return "https://u.gg/lol/champions/aram/" + slug + "-aram";
    },
    augmentUrl: function (champion) {
      var slug = String(champion).toLowerCase().replace(/[^a-z0-9]/g, "");
      return "https://u.gg/lol/champions/aram-mayhem/" + slug + "-aram-mayhem";
    }
  };

  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.MayhemBuild = api;
})(typeof window !== "undefined" ? window : this);
