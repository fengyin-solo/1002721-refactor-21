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
          <td v-for="column in columns" :key="column">
            <button
              v-if="column === '查验编号'"
              class="link"
              type="button"
              @click="openDetail(row)"
            >
              {{ row[column] ?? '—' }}
            </button>
            <template v-else>{{ row[column] ?? '—' }}</template>
          </td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="openAction(action, row)"
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

    <div v-if="actionState.open" class="modal-mask" @click.self="closeAction">
      <div class="modal-card">
        <h3>{{ actionState.action }} · {{ actionState.row?.['查验编号'] }}</h3>
        <label v-for="field in actionState.fields" :key="field" class="modal-field">
          <span>{{ field }}</span>
          <input v-model="actionState.form[field]" type="datetime-local" step="1" />
        </label>
        <label v-if="actionState.action === '登记结果'" class="modal-field">
          <span>查验结果</span>
          <input v-model="actionState.form['查验结果']" placeholder="如：单货相符，予以放行" />
        </label>
        <div class="modal-actions">
          <button class="btn ghost" type="button" @click="closeAction">取消</button>
          <button class="btn primary" type="button" :disabled="actionState.saving" @click="submitAction">
            {{ actionState.saving ? '提交中…' : '确认' }}
          </button>
        </div>
      </div>
    </div>

    <div v-if="detail" class="modal-mask" @click.self="detail = null">
      <div class="modal-card">
        <h3>查验记录详情 · {{ detail['查验编号'] }}</h3>
        <dl class="detail-list">
          <div v-for="column in detailColumns" :key="column" class="detail-row">
            <dt>{{ column }}</dt>
            <dd>{{ detail[column] ?? '—' }}</dd>
          </div>
        </dl>
        <div class="modal-actions">
          <button class="btn primary" type="button" @click="detail = null">关闭</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/customs'
const columns = ["查验编号", "箱号", "查验类型", "查验级别", "开箱时间", "查验结果", "封箱时间", "查验时长", "查验状态"]
const actions = ["安排查验", "登记结果", "安排复验"]
const statuses = ["待查验", "查验中", "已放行", "待复验"]
const stats = [{"label": "待查验箱", "value": 0}, {"label": "查验中箱", "value": 0}, {"label": "已放行箱", "value": 0}]

// 每个环节要录入的时间字段，由后端按原样留存；前端不算时长，只负责提交与展示。
const ACTION_FIELDS: Record<string, string[]> = {
  安排查验: ['开箱时间'],
  登记结果: ['封箱时间'],
  安排复验: ['复验时间', '封箱时间'],
}

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

const detail = ref<Row | null>(null)
const detailColumns = [...columns, '复验时间']

const actionState = reactive<{
  open: boolean
  saving: boolean
  action: string
  row: Row | null
  fields: string[]
  form: Record<string, string>
}>({
  open: false,
  saving: false,
  action: '',
  row: null,
  fields: [],
  form: {},
})

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

function openAction(action: string, row: Row) {
  const fields = ACTION_FIELDS[action] ?? []
  actionState.open = true
  actionState.saving = false
  actionState.action = action
  actionState.row = row
  actionState.fields = fields
  actionState.form = { '查验结果': '' }
  for (const field of fields) {
    actionState.form[field] = ''
  }
}

function closeAction() {
  actionState.open = false
  actionState.row = null
}

async function submitAction() {
  if (!actionState.row) {
    return
  }
  errorMessage.value = ''
  actionState.saving = true
  const values: Record<string, string> = { action: actionState.action }
  for (const [key, value] of Object.entries(actionState.form)) {
    if (value.trim()) {
      values[key] = value.trim()
    }
  }
  try {
    const response = await request(`${ENDPOINT}/${actionState.row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values }),
    })
    const payload = await response.json().catch(() => null) as { ok?: boolean; message?: string } | null
    if (!response.ok || payload?.ok === false) {
      throw new Error(payload?.message || '海关查验动作未生效，请稍后重试')
    }
    closeAction()
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '海关查验操作失败'
  } finally {
    actionState.saving = false
  }
}

async function openDetail(row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}`)
    if (!response.ok) {
      throw new Error('查验记录详情读取失败')
    }
    detail.value = await response.json() as Row
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '查验记录详情读取失败'
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
