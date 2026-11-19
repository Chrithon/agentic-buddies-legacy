<script setup>
// NPC 管理：GET/POST/PUT/DELETE /api/npcs/
// 字段：id、name、model_config(JSONB)、character_prompt、related_world
// 支持按 related_world 筛选；删除会级联删除 MCP 绑定与对话日志
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { npcApi, worldApi, llmProviderApi } from '../api'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const authStore = useAuthStore()

const list = ref([])
const worlds = ref([])
const modelOptions = ref([])
const loading = ref(false)
const filterWorld = ref(null)

const dialogVisible = ref(false)
const submitting = ref(false)
const editingId = ref(null)

const form = reactive({
  name: '',
  simpleTaskModel: '',
  complexTaskModel: '',
  character_prompt: '',
  related_world: null,
})

const worldMap = computed(() => {
  const map = {}
  for (const w of worlds.value) map[w.id] = w.name
  return map
})

async function fetchList() {
  loading.value = true
  try {
    const params = filterWorld.value ? { related_world: filterWorld.value } : undefined
    // axios get 第二参数即 params
    list.value = await npcApi.list(params)
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    loading.value = false
  }
}

async function fetchWorlds() {
  try {
    worlds.value = await worldApi.list()
  } catch (error) {
    ElMessage.error(error.message)
  }
}

async function fetchModelOptions() {
  try {
    const providers = await llmProviderApi.list()
    const options = []
    for (const p of providers) {
      for (const m of p.models || []) {
        options.push({
          value: `${p.provider_id}:${m.name}`,
          label: `${p.show_name} / ${m.name}`,
        })
      }
    }
    modelOptions.value = options
  } catch (error) {
    ElMessage.error(error.message)
  }
}

function openCreate() {
  editingId.value = null
  Object.assign(form, {
    name: '',
    simpleTaskModel: '',
    complexTaskModel: '',
    character_prompt: '',
    related_world: worlds.value[0]?.id ?? null,
  })
  dialogVisible.value = true
}

function openEdit(row) {
  editingId.value = row.id
  Object.assign(form, {
    name: row.name,
    simpleTaskModel: row.model_config?.simple_task_model || '',
    complexTaskModel: row.model_config?.complex_task_model || '',
    character_prompt: row.character_prompt || '',
    related_world: row.related_world,
  })
  dialogVisible.value = true
}

async function handleSubmit() {
  if (!form.name.trim()) {
    ElMessage.warning('名称为必填项')
    return
  }
  if (!form.related_world) {
    ElMessage.warning('请选择所属世界观（必填）')
    return
  }
  if (!form.character_prompt.trim()) {
    ElMessage.warning('角色 Prompt 为必填项')
    return
  }
  const payload = {
    name: form.name,
    model_config: {
      simple_task_model: form.simpleTaskModel || '',
      complex_task_model: form.complexTaskModel || '',
    },
    character_prompt: form.character_prompt,
    related_world: form.related_world,
    owner: authStore.user?.id,
  }
  submitting.value = true
  try {
    if (editingId.value) {
      await npcApi.update(editingId.value, payload)
      ElMessage.success('更新成功')
    } else {
      await npcApi.create(payload)
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

async function handleToggleEnabled(row) {
  const target = !row.is_enabled
  try {
    await npcApi.update(row.id, { is_enabled: target })
    ElMessage.success(target ? `「${row.name}」已启用` : `「${row.name}」已停用`)
    await fetchList()
  } catch (error) {
    ElMessage.error(error.message)
  }
}

async function handleDelete(row) {
  try {
    await ElMessageBox.confirm(
      `确定删除 NPC「${row.name}」吗？其 MCP 绑定与对话日志将被级联删除。`,
      '删除确认',
      { type: 'warning' }
    )
  } catch {
    return
  }
  try {
    await npcApi.remove(row.id)
    ElMessage.success('删除成功')
    await fetchList()
  } catch (error) {
    ElMessage.error(error.message)
  }
}

onMounted(() => {
  fetchList()
  fetchWorlds()
  fetchModelOptions()
})
</script>

<template>
  <el-card>
    <div class="toolbar">
      <h3>NPC 管理</h3>
      <div class="toolbar-right">
        <el-select
          v-model="filterWorld"
          placeholder="按世界观筛选"
          clearable
          style="width: 180px"
          @change="fetchList"
        >
          <el-option
            v-for="w in worlds"
            :key="w.id"
            :label="w.name"
            :value="w.id"
          />
        </el-select>
        <el-button type="primary" @click="openCreate">新建 NPC</el-button>
      </div>
    </div>

    <el-table v-loading="loading" :data="list" stripe>
      <el-table-column prop="name" label="名称" width="160" />
      <el-table-column label="所属世界观" width="150">
        <template #default="{ row }">
          <el-tag v-if="row.related_world" size="small">
            {{ worldMap[row.related_world] || `#${row.related_world}` }}
          </el-tag>
          <span v-else>-</span>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag size="small" :type="row.is_enabled ? 'success' : 'info'">
            {{ row.is_enabled ? '启用' : '停用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="character_prompt" label="角色 Prompt" show-overflow-tooltip />
      <el-table-column label="简单任务模型" width="200" show-overflow-tooltip>
        <template #default="{ row }">
          {{ row.model_config?.simple_task_model || '-' }}
        </template>
      </el-table-column>
      <el-table-column label="复杂任务模型" width="200" show-overflow-tooltip>
        <template #default="{ row }">
          {{ row.model_config?.complex_task_model || '-' }}
        </template>
      </el-table-column>
      <el-table-column label="操作" width="260" fixed="right">
        <template #default="{ row }">
          <el-button
            link
            type="primary"
            @click="router.push({ name: 'npc-detail', params: { id: row.id } })"
          >
            详情
          </el-button>
          <el-button
            link
            type="primary"
            @click="handleToggleEnabled(row)"
          >
            {{ row.is_enabled ? '停用' : '启用' }}
          </el-button>
          <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button link type="danger" @click="handleDelete(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog
      v-model="dialogVisible"
      :title="editingId ? '编辑 NPC' : '新建 NPC'"
      width="640px"
    >
      <el-form label-width="110px">
        <el-form-item label="名称" required>
          <el-input v-model="form.name" />
        </el-form-item>
        <el-form-item label="所属世界观" required>
          <el-select v-model="form.related_world" style="width: 100%">
            <el-option
              v-for="w in worlds"
              :key="w.id"
              :label="w.name"
              :value="w.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="角色 Prompt" required>
          <el-input v-model="form.character_prompt" type="textarea" :rows="5" placeholder="必填" />
        </el-form-item>
        <el-form-item label="简单任务模型">
          <el-select
            v-model="form.simpleTaskModel"
            clearable
            placeholder="选择简单任务模型"
            style="width:100%"
          >
            <el-option
              v-for="o in modelOptions"
              :key="o.value"
              :label="o.label"
              :value="o.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="复杂任务模型">
          <el-select
            v-model="form.complexTaskModel"
            clearable
            placeholder="选择复杂任务模型"
            style="width:100%"
          >
            <el-option
              v-for="o in modelOptions"
              :key="o.value"
              :label="o.label"
              :value="o.value"
            />
          </el-select>
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

.toolbar-right {
  display: flex;
  gap: 12px;
}
</style>
