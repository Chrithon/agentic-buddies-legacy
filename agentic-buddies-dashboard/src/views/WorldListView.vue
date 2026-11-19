<script setup>
// 世界观管理：GET/POST/PUT/DELETE /api/worlds/
// 字段：id、name（唯一）、description、world_prompt、
//       kb_api_url、kb_api_headers(JSONB)、kb_api_timeout、kb_api_data(JSONB)
// 注：被 NPC 引用时后端会拒绝删除
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { worldApi } from '../api'

const list = ref([])
const loading = ref(false)
const dialogVisible = ref(false)
const submitting = ref(false)
const editingId = ref(null)

const form = reactive({
  name: '',
  description: '',
  world_prompt: '',
  kb_api_url: '',
  kbHeadersText: '{}',
  kb_api_timeout: 30,
  kbDataText: '{}',
})

async function fetchList() {
  loading.value = true
  try {
    list.value = await worldApi.list()
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
    description: '',
    world_prompt: '',
    kb_api_url: '',
    kbHeadersText: '{}',
    kb_api_timeout: 30,
    kbDataText: '{\n  "dataset_id": "",\n  "query": "[user_input]",\n  "retrieval_model": {\n    "search_method": "semantic_search",\n    "top_k": 5,\n    "score_threshold_enabled": false\n  },\n  "attachment_ids": []\n}',
  })
  dialogVisible.value = true
}

function openEdit(row) {
  editingId.value = row.id
  Object.assign(form, {
    name: row.name,
    description: row.description || '',
    world_prompt: row.world_prompt,
    kb_api_url: row.kb_api_url || '',
    kbHeadersText: JSON.stringify(row.kb_api_headers ?? {}, null, 2),
    kb_api_timeout: row.kb_api_timeout ?? 30,
    kbDataText: JSON.stringify(row.kb_api_data ?? {}, null, 2),
  })
  dialogVisible.value = true
}

async function handleSubmit() {
  if (!form.name.trim() || !form.world_prompt.trim()) {
    ElMessage.warning('名称和世界观 Prompt 为必填项')
    return
  }
  let kbHeaders
  try {
    kbHeaders = JSON.parse(form.kbHeadersText || '{}')
  } catch {
    ElMessage.error('知识库请求头不是合法的 JSON')
    return
  }
  let kbData
  try {
    kbData = JSON.parse(form.kbDataText || '{}')
  } catch {
    ElMessage.error('知识库请求数据不是合法的 JSON')
    return
  }
  const payload = {
    name: form.name,
    description: form.description || null,
    world_prompt: form.world_prompt,
    kb_api_url: form.kb_api_url || null,
    kb_api_headers: kbHeaders,
    kb_api_timeout: form.kb_api_timeout,
    kb_api_data: kbData,
  }
  submitting.value = true
  try {
    if (editingId.value) {
      await worldApi.update(editingId.value, payload)
      ElMessage.success('更新成功')
    } else {
      await worldApi.create(payload)
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
      `确定删除世界观「${row.name}」吗？`,
      '删除确认',
      { type: 'warning' }
    )
  } catch {
    return
  }
  try {
    await worldApi.remove(row.id)
    ElMessage.success('删除成功')
    await fetchList()
  } catch (error) {
    ElMessage.error(error.message)
  }
}

onMounted(fetchList)
</script>

<template>
  <el-card>
    <div class="toolbar">
      <h3>世界观管理</h3>
      <el-button type="primary" @click="openCreate">新建世界观</el-button>
    </div>

    <el-table v-loading="loading" :data="list" stripe>
      <el-table-column prop="name" label="名称" width="180" />
      <el-table-column prop="description" label="描述" show-overflow-tooltip />
      <el-table-column prop="world_prompt" label="世界观 Prompt" show-overflow-tooltip />
      <el-table-column label="知识库 API" width="180" show-overflow-tooltip>
        <template #default="{ row }">{{ row.kb_api_url || '-' }}</template>
      </el-table-column>
      <el-table-column label="操作" width="150" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button link type="danger" @click="handleDelete(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog
      v-model="dialogVisible"
      :title="editingId ? '编辑世界观' : '新建世界观'"
      width="640px"
    >
      <el-form label-width="110px">
        <el-form-item label="名称" required>
          <el-input v-model="form.name" placeholder="唯一名称" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="世界观 Prompt" required>
          <el-input
            v-model="form.world_prompt"
            type="textarea"
            :rows="8"
            placeholder="注入到 NPC 对话上下文的世界观设定"
          />
        </el-form-item>
        <el-form-item label="知识库 API 地址">
          <el-input v-model="form.kb_api_url" placeholder="知识库检索接口 URL（可选）" />
        </el-form-item>
        <el-form-item label="知识库请求头">
          <el-input
            v-model="form.kbHeadersText"
            type="textarea"
            :rows="4"
            placeholder='JSON 对象，如 {"Authorization": "Bearer xxx"}'
            class="mono"
          />
        </el-form-item>
        <el-form-item label="知识库超时(秒)">
          <el-input-number v-model="form.kb_api_timeout" :min="1" :max="300" />
        </el-form-item>
        <el-form-item label="知识库请求数据">
          <el-input
            v-model="form.kbDataText"
            type="textarea"
            :rows="8"
            placeholder='JSON 对象，如 {"dataset_id": "xxx", "query": "[user_input]", "retrieval_model": {...}}；[user_input] 会替换为用户实际输入'
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
