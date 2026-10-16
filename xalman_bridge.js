const readline = require("readline");

function videoIdFrom(url) {
  const match = String(url).match(/(?:v=|youtu\.be\/|shorts\/|embed\/)([A-Za-z0-9_-]{11})/);
  return match && match[1];
}

async function getJson(base, endpoint, url) {
  const query = new URLSearchParams({ url: String(url) }).toString();
  const response = await fetch(`${base}${endpoint}?${query}`, {
    headers: { Accept: "application/json" },
    signal: AbortSignal.timeout(60000),
  });
  let data = null;
  try { data = await response.json(); } catch (_) {}
  return { status: response.status, data };
}

function directUrl(payload) {
  return payload?.url || payload?.data?.url || payload?.result?.url || payload?.video_url ||
    payload?.data?.video_url || payload?.download?.url || null;
}

async function xalmanDownloads(url) {
  const base = (process.env.XALMAN_API_BASE_URL || "https://xalman-apis.vercel.app").replace(/\/$/, "");
  const requests = [
    { endpoint: "/api/ytmp3", type: "audio", quality: "128kbps" },
    { endpoint: "/api/ytdlv3", type: "video", quality: "360p" },
  ];
  const downloads = [];
  const errors = [];
  let title = "YouTube Video";
  let thumbnail = null;

  for (const request of requests) {
    try {
      const response = await getJson(base, request.endpoint, url);
      if (response.status < 200 || response.status >= 300) {
        errors.push(`${request.endpoint}: HTTP ${response.status}`);
        continue;
      }
      const direct = directUrl(response.data);
      if (!direct) {
        errors.push(`${request.endpoint}: استجابة بلا رابط`);
        continue;
      }
      title = response.data?.title || response.data?.data?.title || title;
      thumbnail = response.data?.thumbnail || response.data?.data?.thumbnail || thumbnail;
      downloads.push({ type: request.type, quality: request.quality, url: direct });
    } catch (error) {
      errors.push(`${request.endpoint}: ${error.message}`);
    }
  }

  // المسار الثالث في توثيق Xalman؛ يستخدم كاحتياط للفيديو إذا لم يُرجع ytdlv3 رابطًا.
  if (!downloads.some((item) => item.type === "video")) {
    try {
      const response = await getJson(base, "/api/ytdl", url);
      const direct = directUrl(response.data);
      if (response.status >= 200 && response.status < 300 && direct) {
        title = response.data?.title || title;
        thumbnail = response.data?.thumbnail || thumbnail;
        downloads.push({ type: "video", quality: response.data?.quality || "360p", url: direct });
      } else {
        errors.push(`/api/ytdl: HTTP ${response.status}`);
      }
    } catch (error) {
      errors.push(`/api/ytdl: ${error.message}`);
    }
  }

  if (!downloads.length) {
    throw new Error(`Xalman لم يُرجع روابط تنزيل (${errors.join("; ") || "استجابة بلا روابط"})`);
  }
  const videoId = videoIdFrom(url);
  return {
    status: true,
    result: {
      title,
      thumbnail: thumbnail || (videoId ? `https://i.ytimg.com/vi/${videoId}/hqdefault.jpg` : null),
      type: "video",
      downloads,
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
  if (!url) throw new Error("Xalman: missing URL");
  process.stdout.write(JSON.stringify(await xalmanDownloads(url)));
}

main().catch((error) => {
  process.stderr.write(String(error && error.stack || error));
  process.exit(1);
});
