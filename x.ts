
import { MiNA, MiIOT } from "mi-service-lite";
import fs from "fs-extra";

async function main() {
  console.log("🔌 正在连接小爱音箱...\n");

  const store = await fs.readJSON(".mi.json");
  const account = store.mina;

  const mi = new MiNA(account);
  const miot = new MiIOT(account);

  console.log("✅ 连接成功！\n");

  // 先检查设备状态
  console.log("📋 当前设备状态:");
  const status = await mi.getStatus();
  console.log(status);
  console.log("");

  // 测试1: 使用 MiIOT TTS 命令
  console.log("🔊 测试1: 播放 TTS (MiIOT doAction)");
  console.log("发送: 你好，小爱同学正在测试");

  // [5, 1] 是 TTS 播放指令
  await miot.doAction(5, 1, "你好，小爱同学正在测试");
  console.log("已发送 TTS 命令");

  // 等待3秒
  await new Promise(resolve => setTimeout(resolve, 3000));

  // 再次检查状态
  const status1 = await mi.getStatus();
  console.log("设备状态:", status1);
  console.log("");

  // 测试2: 使用 MiNA play 方法
  console.log("🔊 测试2: 使用 MiNA play 方法播放 TTS");

  // 使用 MiNA 的文本转语音功能
  await mi.play({ tts: "测试成功，请听到这段话" });
  console.log("已发送 MiNA play 请求");

  await new Promise(resolve => setTimeout(resolve, 5000));

  const status2 = await mi.getStatus();
  console.log("设备状态:", status2);

  // 测试3: 尝试直接使用小爱音箱的内置TTS
  console.log("");
  console.log("🔊 测试3: 直接使用 MiIOT 发送 TTS");

  // 尝试不同的 TTS 命令参数
  await miot.doAction(5, 1, "小爱同学听到了吗");
  console.log("已发送");

  await new Promise(resolve => setTimeout(resolve, 5000));

  console.log("\n📋 最终设备状态:");
  const finalStatus = await mi.getStatus();
  console.log(finalStatus);

  console.log("\n测试完成。如果没有听到声音，请检查：");
  console.log("1. 小爱音箱音量是否开启");
  console.log("2. 音箱是否在线");
  console.log("3. 网络是否能访问小米服务器");
}

main().catch(console.error);
