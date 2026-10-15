const axios = require("axios");
const readline = require("readline");
const { youtube } = require("@coflyn/scrapr");

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function videoIdFrom(url) {
  const match = String(url).match(/(?:v=|youtu\.be\/|shorts\/|embed\/)([A-Za-z0-9_-]{11})/);
  return match && match[1];
}

function findLinks(value, seen = new Set()) {
  if (!value || typeof value !== "object" || seen.has(value)) return [];
  seen.add(value);
  const out = [];
  if (Array.isArray(value)) {
    for (const item of value) out.push(...findLinks(item, seen));
    return out;
  }
  for (const [key, item] of Object.entries(value)) {
    if (typeof item === "string" && /^https?:\/\//i.test(item) &&
        /(url|download|link|audio|video|mp4|mp3|stream)/i.test(key) &&
        !/youtube\.com|youtu\.be|thumbnail|image/i.test(item)) out.push(item);
    else if (item && typeof item === "object") out.push(...findLinks(item, seen));
  }
  return [...new Set(out)];
}

async function kordDownloads(url) {
  const key = process.env.KORD_API_KEY;
  if (!key) return null;
  const client = axios.create({
    baseURL: process.env.KORD_API_BASE_URL || "https://api.kord.live",
    headers: { Authorization: `Bearer ${key}`, Accept: "application/json" },
    timeout: 30000,
  });
  const responses = [];
  for (const request of [
    { path: "/ytmp3", params: { url } },
    { path: "/yt-savetube", params: { url, type: "720" } },
  ]) {
    try {
      const response = await client.get(request.path, { params: request.params });
      if (response.status >= 200 && response.status < 300) responses.push(response.data);
    } catch (_) {}
  }
  const links = [...new Set(responses.flatMap(findLinks))];
  if (!links.length) return null;
  const title = responses.map((x) => x?.title || x?.data?.title || x?.result?.title).find(Boolean) || "YouTube Video";
  return {
    status: true,
    result: {
      title,
      thumbnail: `https://i.ytimg.com/vi/${videoIdFrom(url)}/hqdefault.jpg`,
      type: "video",
      downloads: links.map((link, index) => ({
        type: /mp3|audio/i.test(link) || index === 0 ? "audio" : "video",
        quality: index === 0 ? "mp3" : "720p",
        url: link,
      })),
    },
  };
}

async function legacyYtmp3(url) {
  const videoId = videoIdFrom(url);
  if (!videoId) return null;
  const client = axios.create({
    headers: {
      Origin: "https://ytmp3.mobi", Referer: "https://ytmp3.mobi/en8/",
      "User-Agent": "Mozilla/5.0", Accept: "*/*",
    }, timeout: 15000,
  });
  const init = await client.get(`https://a.ymcdn.org/api/v1/init?p=y&23=1llum1n471&_=${Math.random()}`);
  let data = (await client.get(`${init.data.convertURL}&v=${videoId}&f=mp4&_=${Math.random()}`)).data;
  if (data.redirect > 0 && data.redirectURL) data = (await client.get(`${data.redirectURL}&v=${videoId}&f=mp4&_=${Math.random()}`)).data;
  if (!data || data.error || !data.downloadURL) return null;
  for (let attempt = 0; attempt < 8; attempt++) {
    if (attempt) await sleep(1500);
    try {
      const status = await client.get(`${data.progressURL}&_=${Math.random()}`);
      if (Number(status.data?.progress || 0) >= 1 || status.data?.downloadURL) break;
    } catch (_) {}
  }
  return { status: true, result: { title: data.title || "YouTube Video", thumbnail: `https://i.ytimg.com/vi/${videoId}/hqdefault.jpg`, type: "video", downloads: [{ type: "video", quality: "720p", url: data.downloadURL }] } };
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
  if (!url) throw new Error("YouTube: missing URL");

  const kord = await kordDownloads(url);
  if (kord) { process.stdout.write(JSON.stringify(kord)); return; }

  for (const method of [youtube.ytmp3gg, youtube.ytmp3]) {
    if (typeof method !== "function") continue;
    try {
      const response = await method(url, { format: "mp4", quality: "720p" });
      if (response?.status && response.result?.downloads?.length) {
        process.stdout.write(JSON.stringify(response)); return;
      }
    } catch (_) {}
  }
  const legacy = await legacyYtmp3(url);
  if (!legacy) throw new Error(process.env.KORD_API_KEY ? "Kord API وscrapr لم يُرجعا رابط تنزيل" : "KORD_API_KEY غير مضبوط في Render");
  process.stdout.write(JSON.stringify(legacy));
}

main().catch((error) => {
  process.stderr.write(String(error && error.stack || error));
  process.exit(1);
});
