const readline = require("readline");
const { youtube } = require("@coflyn/scrapr");

async function main() {
  const input = await new Promise((resolve, reject) => {
    let body = "";
    const rl = readline.createInterface({ input: process.stdin });
    rl.on("line", (line) => { body += line; });
    rl.on("close", () => resolve(body));
    rl.on("error", reject);
  });
  const request = JSON.parse(input || "{}");
  const url = String(request.url || "");
  if (!url) throw new Error("scrapr: missing URL");

  let result = null;
  for (const method of [youtube.ytmp3gg, youtube.ytmp3]) {
    if (typeof method !== "function") continue;
    try {
      const response = await method(url, { format: "mp4", quality: "720p" });
      if (response && response.status && response.result && response.result.downloads?.length) {
        result = response;
        break;
      }
    } catch (_) {}
  }
  if (!result) throw new Error("scrapr: no download link returned");
  process.stdout.write(JSON.stringify(result));
}

main().catch((error) => {
  process.stderr.write(String(error && error.stack || error));
  process.exit(1);
});
