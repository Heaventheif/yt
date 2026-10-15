const readline = require("readline");

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

async function getJson(base, path, params, headers) {
  const query = new URLSearchParams(params).toString();
  const response = await fetch(`${base}${path}?${query}`, { headers, signal: AbortSignal.timeout(30000) });
  let data = null;
  try { data = await response.json(); } catch (_) {}
  return { status: response.status, data };
}

async function kordDownloads(url) {
  const base = (process.env.KORD_API_BASE_URL || "https://api.kord.live").replace(/\/$/, "");
  const headers = { Accept: "application/json" };
  if (process.env.KORD_API_KEY) headers.Authorization = `Bearer ${process.env.KORD_API_KEY}`;
  const responses = [];
  const errors = [];
  for (const request of [
    { path: "/ytmp3", params: { url } },
    { path: "/yt-savetube", params: { url, type: "720" } },
  ]) {
    try {
      const response = await getJson(base, request.path, request.params, headers);
      if (response.status >= 200 && response.status < 300) responses.push(response.data);
      else errors.push(`${request.path}: HTTP ${response.status}`);
    } catch (error) {
      errors.push(`${request.path}: ${error.message}`);
    }
  }
  const links = [...new Set(responses.flatMap(findLinks))];
  if (!links.length) throw new Error(`Kord لم يُرجع روابط تنزيل (${errors.join("; ") || "استجابة بلا روابط"})`);
  const videoId = videoIdFrom(url);
  const title = responses.map((x) => x?.title || x?.data?.title || x?.result?.title).find(Boolean) || "YouTube Video";
  return {
    status: true,
    result: {
      title,
      thumbnail: videoId ? `https://i.ytimg.com/vi/${videoId}/hqdefault.jpg` : null,
      type: "video",
      downloads: links.map((link, index) => ({
        type: /mp3|audio/i.test(link) || index === 0 ? "audio" : "video",
        quality: index === 0 ? "mp3" : "720p",
        url: link,
      })),
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
  if (!url) throw new Error("Kord: missing URL");
  process.stdout.write(JSON.stringify(await kordDownloads(url)));
}

main().catch((error) => {
  process.stderr.write(String(error && error.stack || error));
  process.exit(1);
});
