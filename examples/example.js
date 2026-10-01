// node examples/example.js "https://youtu.be/VIDEO_ID"
// المتغيرات: YTDLP_URL (رابط الخدمة)، YTDLP_KEY (المفتاح)
const { YtdlpClient, YtdlpApiError } = require("./client");

(async () => {
  const api = new YtdlpClient(process.env.YTDLP_URL, process.env.YTDLP_KEY);
  const url = process.argv[2];

  const info = await api.info(url);
  console.log(info.title, "—", info.video.map((v) => v.label).join(" | "));

  const { path, bytes } = await api.download(url, {
    type: "video", q: 480, dir: "./downloads",
    onProgress: (got, total) =>
      process.stdout.write(`\r${(got / 1048576).toFixed(1)}MB${total ? ` / ${(total / 1048576).toFixed(1)}MB` : ""}`),
  });
  console.log(`\nتم: ${path} (${bytes} بايت)`);
})().catch((e) => {
  console.error(e instanceof YtdlpApiError ? `خطأ ${e.status}: ${e.message}` : e);
  process.exit(1);
});
