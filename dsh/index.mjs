// selfstill-dsh：把 selfstill 蒸馏工作流注册为 DSH 运行时 skill。
// 零依赖：不 import 任何 @deepseek-ai/* 包（profile pnpm 闭包注入官方包，声明反而会解析失败）；
// skill 正文从包内读取（单一事实源在 dsh/skills/selfstill/SKILL.md）。
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

export const name = 'selfstill-dsh'
export const inject = ['skills']

function stripFrontmatter(md) {
  if (!md.startsWith('---')) return md
  const end = md.indexOf('\n---', 4)
  if (end === -1) return md
  return md.slice(end + 4).replace(/^\n+/, '')
}

export function apply(ctx) {
  const base = new URL('./skills/selfstill/', import.meta.url)
  const content = stripFrontmatter(readFileSync(new URL('SKILL.md', base), 'utf-8'))
  ctx.effect(() => ctx.skills.register({
    name: 'selfstill',
    description: '把用户与 AI 的聊天记录蒸馏成 L1–L4 个人档案（selfstill 工作流）：整理导出、提炼候选、逐条确认、构建 HTML、写回 DSH 或 Codex/Hermes。',
    whenToUse: '用户要蒸馏聊天记录、建立或更新 L1–L4 个人档案、运行 selfstill 流程，或提到 selfstill / 蒸馏 / 个人档案时使用。',
    source: 'runtime',
    content,
    resourceBase: { kind: 'directory', path: fileURLToPath(base) },
  }))
}
