<script setup>
// LLM 提供商管理：GET/POST/PUT/DELETE /api/llm-providers/
// 字段：id、provider_id（唯一）、show_name、api_key、base_url、models(JSONB 数组)
// api_key 在列表中脱敏展示
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { llmProviderApi } from '../api'

const list = ref([])
const loading = ref(false)
const dialogVisible = ref(false)
const submitting = ref(false)
const editingId = ref(null)

const form = reactive({
  provider_id: '',
  show_name: '',
  api_key: '',
  base_url: '',
  modelRows: [], // [{ name: '' }]，与后端 models 格式一致
})

const fetchingModels = ref(false)

function addModel() {
  form.modelRows.push({ name: '' })
}

function removeModel(index) {
  form.modelRows.splice(index, 1)
}

async function handleFetchModels() {
  if (!form.base_url.trim()) {
    ElMessage.warning('请先填写 Base URL')
    return
  }
  fetchingModels.value = true
  try {
    const data = await llmProviderApi.fetchModels(form.base_url, form.api_key)
    form.modelRows = data.models.map((m) => ({ name: m.name }))
    ElMessage.success(`成功拉取 ${data.models.length} 个模型`)
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    fetchingModels.value = false
  }
}

function maskApiKey(key) {
  if (!key) return '-'
  if (key.length <= 8) return '****'
  return `${key.slice(0, 4)}****${key.slice(-4)}`
}

async function fetchList() {
  loading.value = true
  try {
    list.value = await llmProviderApi.list()
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editingId.value = null
  Object.assign(form, {
    provider_id: '',
    show_name: '',
    api_key: '',
    base_url: '',
    modelRows: [],
  })
  dialogVisible.value = true
}

function openEdit(row) {
  editingId.value = row.id
  Object.assign(form, {
    provider_id: row.provider_id,
    show_name: row.show_name,
    api_key: row.api_key || '',
    base_url: row.base_url || '',
    modelRows: (row.models ?? []).map((m) => ({
      name: m.name ?? '',
    })),
  })
  dialogVisible.value = true
}

async function handleSubmit() {
  if (!form.provider_id.trim() || !form.show_name.trim()) {
    ElMessage.warning('provider_id 和显示名称为必填项')
    return
  }
  const modelRows = form.modelRows
    .map((m) => ({ name: (m.name || '').trim() }))
    .filter((m) => m.name)
  if (modelRows.length !== form.modelRows.length) {
    ElMessage.warning('存在空的模型条目，请填写或删除')
    return
  }
  const payload = {
    provider_id: form.provider_id,
    show_name: form.show_name,
    api_key: form.api_key || null,
    base_url: form.base_url || null,
    models: modelRows,
  }
  submitting.value = true
  try {
    if (editingId.value) {
      await llmProviderApi.update(editingId.value, payload)
      ElMessage.success('更新成功')
    } else {
      await llmProviderApi.create(payload)
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
      `确定删除提供商「${row.show_name}」吗？`,
      '删除确认',
      { type: 'warning' }
    )
  } catch {
    return
  }
  try {
    await llmProviderApi.remove(row.id)
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
      <h3>LLM 提供商</h3>
      <el-button type="primary" @click="openCreate">新建提供商</el-button>
    </div>

    <el-table v-loading="loading" :data="list" stripe>
      <el-table-column prop="provider_id" label="标识" width="140" />
      <el-table-column prop="show_name" label="显示名称" width="150" />
      <el-table-column label="API Key" width="160">
        <template #default="{ row }">
          <code>{{ maskApiKey(row.api_key) }}</code>
        </template>
      </el-table-column>
      <el-table-column prop="base_url" label="Base URL" show-overflow-tooltip />
      <el-table-column label="模型" min-width="200">
        <template #default="{ row }">
          <template v-if="Array.isArray(row.models) && row.models.length">
            <el-tag
              v-for="m in row.models.slice(0, 2)"
              :key="m.name"
              size="small"
              class="model-tag"
            >
              {{ m.name }}
            </el-tag>
            <span v-if="row.models.length > 2" class="models-more">
              等{{ row.models.length }}个
            </span>
          </template>
          <span v-else>-</span>
        </template>
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
      :title="editingId ? '编辑提供商' : '新建提供商'"
      width="640px"
    >
      <el-form label-width="110px">
        <el-form-item label="标识" required>
          <el-input v-model="form.provider_id" placeholder="如 deepseek" />
        </el-form-item>
        <el-form-item label="显示名称" required>
          <el-input v-model="form.show_name" placeholder="如 DeepSeek" />
        </el-form-item>
        <el-form-item label="API Key">
          <el-input
            v-model="form.api_key"
            type="password"
            show-password
            placeholder="留空表示不设置"
          />
        </el-form-item>
        <el-form-item label="Base URL">
          <el-input v-model="form.base_url" placeholder="如 https://api.deepseek.com" />
        </el-form-item>
        <el-form-item label="模型列表">
          <div class="models-field">
            <div class="models-actions">
              <el-button :loading="fetchingModels" @click="handleFetchModels">
                获取模型
              </el-button>
              <el-button type="primary" plain @click="addModel">添加模型</el-button>
            </div>
            <el-table :data="form.modelRows" size="small" border max-height="280">
              <el-table-column type="index" label="#" width="50" />
              <el-table-column label="模型名称">
                <template #default="{ row }">
                  <el-input v-model="row.name" placeholder="如 deepseek-chat" size="small" />
                </template>
              </el-table-column>
              <el-table-column label="操作" width="80" align="center">
                <template #default="{ $index }">
                  <el-button type="danger" link @click="removeModel($index)">删除</el-button>
                </template>
              </el-table-column>
              <template #empty>
                暂无模型，点击"获取模型"从提供商拉取或手动添加
              </template>
            </el-table>
          </div>
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

.models-field {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.models-actions {
  display: flex;
  gap: 8px;
}

.model-tag {
  margin: 2px 4px 2px 0;
}

.models-more {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  cursor: default;
}
</style>
