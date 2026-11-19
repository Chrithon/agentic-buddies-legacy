<script setup>
// MCP 服务管理：GET/POST/PUT/DELETE /api/mcp/
// 字段：id、name（唯一）、type(sse/streamable-http)、url、headers(JSONB)、timeout
// 被 NPC 引用时后端拒绝删除；可查看引用该 MCP 的 NPC：GET /api/mcp/:id/npcs
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { mcpApi } from '../api'

const list = ref([])
const loading = ref(false)
const dialogVisible = ref(false)
const submitting = ref(false)
const editingId = ref(null)

const npcDialogVisible = ref(false)
const npcList = ref([])
const npcDialogTitle = ref('')

const form = reactive({
  name: '',
  type: 'streamable-http',
  url: '',
  headersText: '{}',
  timeout: 60,
})

async function fetchList() {
  loading.value = true
  try {
    list.value = await mcpApi.list()
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editingId.value = null
  Object.assign(form, {
    name: '',
    type: 'streamable-http',
    url: '',
    headersText: '{}',
    timeout: 60,
  })
  dialogVisible.value = true
}

function openEdit(row) {
  editingId.value = row.id
  Object.assign(form, {
    name: row.name,
    type: row.type,
    url: row.url,
    headersText: JSON.stringify(row.headers ?? {}, null, 2),
    timeout: row.timeout,
  })
  dialogVisible.value = true
}

async function handleSubmit() {
  if (!form.name.trim() || !form.url.trim()) {
    ElMessage.warning('名称和 URL 为必填项')
    return
  }
  let headers
  try {
    headers = JSON.parse(form.headersText || '{}')
  } catch {
    ElMessage.error('请求头不是合法的 JSON')
    return
  }
  const payload = {
    name: form.name,
    type: form.type,
    url: form.url,
    headers,
    timeout: form.timeout,
  }
  submitting.value = true
  try {
    if (editingId.value) {
      await mcpApi.update(editingId.value, payload)
      ElMessage.success('更新成功')
    } else {
      await mcpApi.create(payload)
      ElMessage.success('创建成功')
    }
    dialogVisible.value = false
    await fetchList()
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    submitting.value = false
  }
}

async function handleDelete(row) {
  try {
    await ElMessageBox.confirm(
      `确定删除 MCP「${row.name}」吗？被 NPC 引用时将无法删除。`,
      '删除确认',
      { type: 'warning' }
    )
  } catch {
    return
  }
  try {
    await mcpApi.remove(row.id)
    ElMessage.success('删除成功')
    await fetchList()
  } catch (error) {
    ElMessage.error(error.message)
  }
}

async function showReferencedNpcs(row) {
  npcDialogTitle.value = `引用「${row.name}」的 NPC`
  npcDialogVisible.value = true
  try {
    npcList.value = await mcpApi.referencedNpcs(row.id)
  } catch (error) {
    ElMessage.error(error.message)
  }
}

onMounted(fetchList)
</script>

<template>
  <el-card>
    <div class="toolbar">
      <h3>MCP 服务</h3>
      <el-button type="primary" @click="openCreate">新建 MCP</el-button>
    </div>

    <el-table v-loading="loading" :data="list" stripe>
      <el-table-column prop="name" label="名称" width="180" />
      <el-table-column prop="type" label="类型" width="150">
        <template #default="{ row }">
          <el-tag size="small" :type="row.type === 'sse' ? 'success' : 'primary'">
            {{ row.type }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="url" label="URL" show-overflow-tooltip />
      <el-table-column prop="timeout" label="超时(秒)" width="100" />
      <el-table-column label="操作" width="220" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="showReferencedNpcs(row)">
            引用 NPC
          </el-button>
          <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button link type="danger" @click="handleDelete(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog
      v-model="dialogVisible"
      :title="editingId ? '编辑 MCP' : '新建 MCP'"
      width="640px"
    >
      <el-form label-width="100px">
        <el-form-item label="名称" required>
          <el-input v-model="form.name" placeholder="唯一名称" />
        </el-form-item>
        <el-form-item label="类型" required>
          <el-radio-group v-model="form.type">
            <el-radio value="streamable-http">streamable-http</el-radio>
            <el-radio value="sse">sse</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="URL" required>
          <el-input v-model="form.url" placeholder="MCP 服务地址" />
        </el-form-item>
        <el-form-item label="超时(秒)">
          <el-input-number v-model="form.timeout" :min="1" :max="600" />
        </el-form-item>
        <el-form-item label="请求头">
          <el-input
            v-model="form.headersText"
            type="textarea"
            :rows="5"
            placeholder='JSON 对象，如 {"Authorization": "Bearer xxx"}'
            class="mono"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="handleSubmit">
          保存
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="npcDialogVisible" :title="npcDialogTitle" width="480px">
      <el-table :data="npcList" size="small">
        <el-table-column prop="name" label="名称" />
        <template #empty>没有 NPC 引用该 MCP</template>
      </el-table>
    </el-dialog>
  </el-card>
</template>

<style scoped>
.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.toolbar h3 {
  margin: 0;
}

.mono :deep(textarea) {
  font-family: monospace;
}
</style>
