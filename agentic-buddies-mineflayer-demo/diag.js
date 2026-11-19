// 临时诊断脚本：观察 knight 是否在跟随玩家
const mineflayer = require('mineflayer')

const bot = mineflayer.createBot({
  host: process.env.MC_HOST || 'localhost',
  port: Number(process.env.MC_PORT || 25565),
  username: 'abdiag',
  auth: 'offline',
})

bot.on('spawn', () => {
  console.log('[diag] 已进入世界')
  setTimeout(() => {
    const players = Object.values(bot.players)
      .filter((p) => p.username !== bot.username)
      .map((p) => ({
        name: p.username,
        pos: p.entity ? [Math.round(p.entity.position.x), p.entity.position.y, Math.round(p.entity.position.z)] : '无实体',
        ping: p.ping,
      }))
    console.log('[diag] 在线玩家:', JSON.stringify(players))

    // 找 knight
    const knight = Object.values(bot.players).find((p) => p.username === 'knight')
    if (knight && knight.entity) {
      console.log('[diag] knight 位置:', JSON.stringify([Math.round(knight.entity.position.x), knight.entity.position.y, Math.round(knight.entity.position.z)]))
    } else {
      console.log('[diag] knight 不在视野内或未在线')
    }
  }, 2000)

  // 观察 20 秒位置变化
  let last = null
  const timer = setInterval(() => {
    const knight = Object.values(bot.players).find((p) => p.username === 'knight')
    if (knight && knight.entity) {
      const pos = [Math.round(knight.entity.position.x), knight.entity.position.y, Math.round(knight.entity.position.z)]
      if (last && JSON.stringify(pos) !== JSON.stringify(last)) {
        console.log('[diag] knight 移动了:', JSON.stringify(pos))
      }
      last = pos
    }
    const players = Object.values(bot.players).filter((p) => p.username !== bot.username && p.username !== 'knight' && p.entity)
    if (players.length) {
      const p = players[0]
      const d = p.entity.position.distanceTo(knight?.entity?.position)
      console.log(`[diag] 玩家 ${p.username} 距 knight: ${d ? Math.round(d) : '?'} 格`)
    }
  }, 3000)
  setTimeout(() => { clearInterval(timer); console.log('[diag] 观察结束'); bot.end(); process.exit(0) }, 20000)
})

bot.on('error', (err) => { console.error('[diag] 错误:', err.message); process.exit(1) })
