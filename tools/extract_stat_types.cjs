/*
 * One-off generator: copies the NKM_STAT_TYPE enum out of the Mod:Side source
 * verbatim into a JSON data file, so the Python port cannot drift from it.
 * Run with: node tools/extract_stat_types.cjs
 */
const fs = require("fs");
const path = require("path");

const REPO = process.env.CS_SOURCE_REPO || "/home/windows/project/RevivalSide";
const OUT = path.join(__dirname, "..", "src", "counterside_mcp", "data", "nkm_stat_type.json");

const codec = fs.readFileSync(path.join(REPO, "modules/packet-codec/index.js"), "utf8");
const freezeAt = codec.indexOf("NKM_STAT_TYPE");
if (freezeAt < 0) throw new Error("NKM_STAT_TYPE not found");
const braceStart = codec.indexOf("{", codec.indexOf("Object.freeze", freezeAt));

let depth = 0;
let i = braceStart;
for (; i < codec.length; i++) {
  if (codec[i] === "{") depth++;
  else if (codec[i] === "}") {
    depth--;
    if (depth === 0) break;
  }
}
const body = codec.slice(braceStart + 1, i);

const out = {};
for (const line of body.split("\n")) {
  const kv = line.match(/^\s*(NST_[A-Za-z0-9_]+)\s*:\s*(-?\d+)\s*,?/);
  if (kv) out[kv[1]] = Number(kv[2]);
}

fs.mkdirSync(path.dirname(OUT), { recursive: true });
fs.writeFileSync(OUT, JSON.stringify(out, null, 2) + "\n");
console.log("wrote", Object.keys(out).length, "stat types to", OUT);
