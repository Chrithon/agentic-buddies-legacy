<script setup>
// 对话日志：GET /api/logs/（只读）
// 筛选：npc_role_id、session_uuid、flagged；分页：limit/offset
// 详情：GET /api/logs/:id
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { chatLogApi, npcApi } from '../api'

const list = ref([])
const npcs = ref([])
const loading = ref(false)

const PAGE_SIZE = 20

const filters = reactive({
  npc_role_id: null,
  session_uuid: '',
  flagged: null,
  alert_required: null,
})

const pagination = reactive({
  page: 1,
  limit: PAGE_SIZE,
})

// 后端列表接口未返回总数，以"本页是否满"判断是否还有下一页
const hasMore = ref(false)

const detailVisible = ref(false)
const detail = ref(null)
const detailLoading = ref(false)

const FLAGGED_CATEGORY_LABELS = {
  political: '政治',
  sexual: '色情',
  violence: '暴力',
  custom: '自定义',
}

const TASK_TYPE_LABELS = {
  simple: '简单任务',
  complex: '复杂任务',
  chat: '闲聊',
}

const BEHAVIOR_SOURCE_LABELS = {
  llm: 'LLM 生成',
  template: '模板兜底',
  none: '无',
}

function npcName(id) {
  const npc = npcs.value.find((n) => n.id === id)
  return npc ? npc.name : `#${id}`
}

function formatTime(value) {
  return value ? new Date(value).toLocaleString('zh-CN') : '-'
}

async function fetchList() {
  loading.value = true
  try {
    const params = {
      limit: pagination.limit,
      offset: (pagination.page - 1) * pagination.limit,
    }
    if (filters.npc_role_id) params.npc_role_id = filters.npc_role_id
    if (filters.session_uuid.trim()) params.session_uuid = filters.session_uuid.trim()
    if (filters.flagged !== null) params.flagged = filters.flagged
    if (filters.alert_required !== null) params.alert_required = filters.alert_required
    const data = await chatLogApi.list(params)
    list.value = data
    hasMore.value = data.length === pagination.limit
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    loading.value = false
  }
}

function handleSearch() {
  pagination.page = 1
  fetchList()
}

function handleReset() {
  filters.npc_role_id = null
  filters.session_uuid = ''
  filters.flagged = null
  filters.alert_required = null
  handleSearch()
}

function changePage(delta) {
  pagination.page += delta
  fetchList()
}

async function showDetail(row) {
  detailVisible.value = true
  detailLoading.value = true
  try {
    detail.value = await chatLogApi.detail(row.id)
  } catch (error) {
    ElMessage.error(error.message)
    detailVisible.value = false
  } finally {
    detailLoading.value = false
  }
}

async function fetchNpcs() {
  try {
    npcs.value = await npcApi.list()
  } catch (error) {
    ElMessage.error(error.message)
  }
}

onMounted(() => {
  fetchList()
  fetchNpcs()
})
</script>

<template>
  <el-card>
    <div class="toolbar">
      <h3>对话日志</h3>
      <div class="toolbar-right">
        <el-select
          v-model="filters.npc_role_id"
          placeholder="按 NPC 筛选"
          clearable
          style="width: 150px"
        >
          <el-option v-for="n in npcs" :key="n.id" :label="n.name" :value="n.id" />
        </el-select>
        <el-input
          v-model="filters.session_uuid"
          placeholder="会话 UUID"
          clearable
          style="width: 220px"
          @keyup.enter="handleSearch"
        />
        <el-select
          v-model="filters.flagged"
          placeholder="安全拦截"
          clearable
          style="width: 130px"
        >
          <el-option label="已拦截" :value="true" />
          <el-option label="未拦截" :value="false" />
        </el-select>
        <el-select
          v-model="filters.alert_required"
          placeholder="需告警"
          clearable
          style="width: 120px"
        >
          <el-option label="是" :value="true" />
          <el-option label="否" :value="false" />
        </el-select>
        <el-button type="primary" @click="handleSearch">查询</el-button>
        <el-button @click="handleReset">重置</el-button>
      </div>
    </div>

    <el-table v-loading="loading" :data="list" stripe>
      <el-table-column label="NPC" width="120">
        <template #default="{ row }">{{ npcName(row.npc_role_id) }}</template>
      </el-table-column>
      <el-table-column prop="player_input" label="玩家输入" show-overflow-tooltip />
      <el-table-column prop="npc_response" label="NPC 回复" show-overflow-tooltip />
      <el-table-column label="任务类型" width="95">
        <template #default="{ row }">
          <el-tag size="small" :type="row.exec_step?.route?.task_type === 'chat' ? 'info' : 'primary'">
            {{ TASK_TYPE_LABELS[row.exec_step?.route?.task_type] || '-' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="耗时" width="90">
        <template #default="{ row }">
          {{ row.latency_ms != null ? `${row.latency_ms}ms` : '-' }}
        </template>
      </el-table-column>
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag size="small" :type="row.success ? 'success' : 'danger'">
            {{ row.success ? '成功' : '失败' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="拦截" width="110">
        <template #default="{ row }">
          <el-tag v-if="row.flagged" size="small" type="warning">
            {{ FLAGGED_CATEGORY_LABELS[row.flagged_category] || '已拦截' }}
          </el-tag>
          <span v-else>-</span>
        </template>
      </el-table-column>
      <el-table-column label="需告警" width="85" align="center">
        <template #default="{ row }">
          <el-tag size="small" :type="row.alert_required ? 'danger' : 'info'">
            {{ row.alert_required ? '是' : '否' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="时间" width="170">
        <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="90" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="showDetail(row)">详情</el-button>
        </template>
      </el-table-column>
    </el-table>

    <div class="pagination">
      <el-button :disabled="pagination.page <= 1" @click="changePage(-1)">
        上一页
      </el-button>
      <span class="page-info">第 {{ pagination.page }} 页</span>
      <el-button :disabled="!hasMore" @click="changePage(1)">下一页</el-button>
    </div>

    <el-dialog v-model="detailVisible" title="日志详情" width="720px">
      <div v-loading="detailLoading">
        <template v-if="detail">
          <el-descriptions :column="2" border>
          <el-descriptions-item label="NPC">
            {{ npcName(detail.npc_role_id) }}
          </el-descriptions-item>
          <el-descriptions-item label="玩家 UUID" :span="2">
            {{ detail.player_uuid || '-' }}
          </el-descriptions-item>
          <el-descriptions-item label="会话 UUID" :span="2">
            {{ detail.session_uuid || '-' }}
          </el-descriptions-item>
          <el-descriptions-item label="玩家输入" :span="2">
            <pre class="content">{{ detail.player_input }}</pre>
          </el-descriptions-item>
          <el-descriptions-item label="NPC 回复" :span="2">
            <pre class="content">{{ detail.npc_response }}</pre>
          </el-descriptions-item>
          <el-descriptions-item label="耗时">
            {{ detail.latency_ms != null ? `${detail.latency_ms}ms` : '-' }}
          </el-descriptions-item>
          <el-descriptions-item label="时间">
            {{ formatTime(detail.created_at) }}
          </el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag size="small" :type="detail.success ? 'success' : 'danger'">
              {{ detail.success ? '成功' : '失败' }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="安全拦截">
            <el-tag v-if="detail.flagged" size="small" type="warning">
              {{ FLAGGED_CATEGORY_LABELS[detail.flagged_category] || '已拦截' }}
            </el-tag>
            <span v-else>未触发</span>
          </el-descriptions-item>
          <el-descriptions-item label="需告警">
            <el-tag size="small" :type="detail.alert_required ? 'danger' : 'info'">
              {{ detail.alert_required ? '是' : '否' }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item v-if="detail.error_message" label="错误信息" :span="2">
            <pre class="content error">{{ detail.error_message }}</pre>
          </el-descriptions-item>
          <el-descriptions-item label="模型配置" :span="2">
            <pre class="content">{{ JSON.stringify(detail.model_config ?? detail.config, null, 2) }}</pre>
            </el-descriptions-item>
          </el-descriptions>

          <template v-if="detail.exec_step">
            <h4 class="exec-title">执行步骤</h4>
          <el-descriptions :column="2" border size="small">
            <el-descriptions-item label="审核分支">
              <el-tag size="small" :type="detail.exec_step.moderation?.mode === 'cloud' ? 'primary' : 'info'">
                {{ detail.exec_step.moderation?.mode === 'cloud' ? '云端' : '本地' }}
              </el-tag>
              <span v-if="detail.exec_step.moderation?.blocked" class="exec-warn">
                （已拦截{{ detail.exec_step.moderation?.category ? `: ${detail.exec_step.moderation.category}` : '' }}）
              </span>
              <span v-else-if="detail.exec_step.moderation?.warning" class="exec-warn">
                （警告注入{{ detail.exec_step.route?.forced_by_warning ? '，已强制走聊天分支' : '' }}）
              </span>
            </el-descriptions-item>
            <el-descriptions-item label="任务类型">
              {{ TASK_TYPE_LABELS[detail.exec_step.route?.task_type] || '-' }}
            </el-descriptions-item>
            <el-descriptions-item label="所用 MCP">
              {{ detail.exec_step.route?.selected_mcp?.length ? detail.exec_step.route.selected_mcp.join('、') : '无' }}
            </el-descriptions-item>
            <el-descriptions-item label="所用行为树">
              {{ detail.exec_step.route?.selected_behaviors?.length ? detail.exec_step.route.selected_behaviors.join('、') : '无' }}
            </el-descriptions-item>
            <el-descriptions-item label="行为来源">
              <el-tag size="small" :type="detail.exec_step.execution?.behavior_source === 'none' ? 'info' : 'success'">
                {{ BEHAVIOR_SOURCE_LABELS[detail.exec_step.execution?.behavior_source] || '-' }}
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="所用模型">
              <template v-if="detail.exec_step.execution?.model_name">
                <el-tag size="small" :type="detail.exec_step.execution.model_used === 'complex' ? 'warning' : 'success'">
                  {{ detail.exec_step.execution.model_used === 'complex' ? '复杂模型' : '简单模型' }}
                </el-tag>
                <code class="exec-model">{{ detail.exec_step.execution.model_name }}</code>
              </template>
              <span v-else>-</span>
            </el-descriptions-item>
            <el-descriptions-item label="OOC 审查">
              <span v-if="detail.exec_step.ooc?.is_ooc">
                <el-tag size="small" type="warning">越界</el-tag>
                <span v-if="detail.exec_step.ooc?.retried">（已重生成）</span>
                <span v-if="detail.exec_step.ooc?.fallback_used">（已兜底）</span>
              </span>
              <el-tag v-else size="small" type="success">未越界</el-tag>
            </el-descriptions-item>
          </el-descriptions>
          </template>
        </template>
      </div>
    </el-dialog>
  </el-card>
</template>

<style scoped>
.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  flex-wrap: wrap;
  gap: 12px;
}

.toolbar h3 {
  margin: 0;
}

.toolbar-right {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.pagination {
  margin-top: 16px;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 12px;
}

.page-info {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.content {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-all;
  font-size: 13px;
}

.content.error {
  color: var(--el-color-danger);
}

.exec-title {
  margin: 16px 0 8px;
  font-size: 14px;
}

.exec-warn {
  margin-left: 6px;
  font-size: 12px;
  color: var(--el-color-warning);
}

.exec-model {
  margin-left: 6px;
  font-size: 12px;
}
</style>
