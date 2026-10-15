const axios = require("axios");
const readline = require("readline");
const { youtube } = require("@coflyn/scrapr");

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function legacyYtmp3(url) {
  const match = url.match(/(?:v=|youtu\.be\/|shorts\/|embed\/)([A-Za-z0-9_-]{11})/);
  const videoId = match && match[1];
  if (!videoId) return null;
  const client = axios.create({
    headers: {
      Origin: "https://ytmp3.mobi",
      Referer: "https://ytmp3.mobi/en8/",
      "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128.0.0.0 Safari/537.36",
      Accept: "*/*",
    },
    timeout: 15000,
  });
  const init = await client.get(`https://a.ymcdn.org/api/v1/init?p=y&23=1llum1n471&_=${Math.random()}`);
  let converted = await client.get(`${init.data.convertURL}&v=${videoId}&f=mp4&_=${Math.random()}`);
  let data = converted.data;
  if (data.redirect > 0 && data.redirectURL) {
    data = (await client.get(`${data.redirectURL}&v=${videoId}&f=mp4&_=${Math.random()}`)).data;
  }
  if (!data || data.error || !data.downloadURL) return null;

  // ytmp3.mobi exposes a usable redirect before its progress reaches 3.
  // Check briefly, but do not discard a valid downloadURL because of a stale counter.
  let progress = 0;
  for (let attempt = 0; attempt < 8; attempt++) {
    if (attempt) await sleep(1500);
    try {
      const status = await client.get(`${data.progressURL}&_=${Math.random()}`);
      progress = Number(status.data?.progress || 0);
      if (progress >= 1 || status.data?.downloadURL) break;
    } catch (_) {}
  }
  return {
    status: true,
    result: {
      title: data.title || "YouTube Video",
      thumbnail: `https://i.ytimg.com/vi/${videoId}/hqdefault.jpg`,
      type: "video",
      downloads: [{ type: "video", quality: "720p", url: data.downloadURL }],
    },
  };
}

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

  for (const method of [youtube.ytmp3gg, youtube.ytmp3]) {
    if (typeof method !== "function") continue;
    try {
      const response = await method(url, { format: "mp4", quality: "720p" });
      if (response && response.status && response.result && response.result.downloads?.length) {
        process.stdout.write(JSON.stringify(response));
        return;
      }
    } catch (_) {}
  }

  const legacy = await legacyYtmp3(url);
  if (!legacy) throw new Error("scrapr: no download link returned");
  process.stdout.write(JSON.stringify(legacy));
}

main().catch((error) => {
  process.stderr.write(String(error && error.stack || error));
  process.exit(1);
});
