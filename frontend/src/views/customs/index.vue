<template>
  <section class="page" data-module="customs">
    <header class="page-head">
      <div>
        <h2>海关查验管理</h2>
        <p class="page-desc">维护查验记录，围绕查验编号、箱号、查验类型、查验级别做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记查验记录</button>
        <button class="btn" type="button" @click="exportRows">导出海关查验清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无海关查验数据，可先登记查验记录</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条海关查验记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/customs'
const columns = ["查验编号", "箱号", "查验类型", "查验级别", "开箱时间", "查验结果", "封箱时间", "查验时长", "查验状态"]
const actions = ["安排查验", "登记结果", "安排复验"]
const statuses = ["待查验", "查验中", "已放行", "待复验"]
const stats = [{"label": "待查验箱", "value": 0}, {"label": "查验中箱", "value": 0}, {"label": "已放行箱", "value": 0}]

// 每个环节登记的时间字段都收敛到后端同一套换算，前端只负责把录入值原样带上。
const ACTION_TIME_LABEL: Record<string, string> = {
  安排查验: '开箱时间',
  登记结果: '封箱时间',
  安排复验: '复验时间',
}

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '查验记录登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  const timeLabel = ACTION_TIME_LABEL[action] ?? '时间'
  const input = window.prompt(`请输入${action}的${timeLabel}（本地时间，如 2026-09-01 23:50；留空按待补录处理）`)
  if (input === null) {
    return
  }
  const values: Record<string, string> = { action }
  if (input.trim()) {
    values[timeLabel] = input.trim()
  }
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values }),
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok || payload?.ok === false) {
      throw new Error(payload?.message ?? '海关查验动作未生效，请稍后重试')
    }
    errorMessage.value = payload?.message ?? ''
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '海关查验操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('查验记录列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '海关查验列表读取失败'
  }
}

onMounted(reload)
</script>
