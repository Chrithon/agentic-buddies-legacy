<script setup>
// 行为树管理：GET/POST/PUT/DELETE /api/behavior-trees/
// 字段：id、name、description、tree_definition(JSONB)
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { behaviorTreeApi } from '../api'

const list = ref([])
const loading = ref(false)
const dialogVisible = ref(false)
const submitting = ref(false)
const editingId = ref(null)

const form = reactive({
  name: '',
  description: '',
  treeDefinitionText: '{}',
})

async function fetchList() {
  loading.value = true
  try {
    list.value = await behaviorTreeApi.list()
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editingId.value = null
  Object.assign(form, { name: '', description: '', treeDefinitionText: '{}' })
  dialogVisible.value = true
}

function openEdit(row) {
  editingId.value = row.id
  Object.assign(form, {
    name: row.name,
    description: row.description || '',
    treeDefinitionText: JSON.stringify(row.tree_definition ?? {}, null, 2),
  })
  dialogVisible.value = true
}

async function handleSubmit() {
  if (!form.name.trim()) {
    ElMessage.warning('名称为必填项')
    return
  }
  let treeDefinition
  try {
    treeDefinition = JSON.parse(form.treeDefinitionText || '{}')
  } catch {
    ElMessage.error('行为树定义不是合法的 JSON')
    return
  }
  const payload = {
    name: form.name,
    description: form.description || null,
    tree_definition: treeDefinition,
  }
  submitting.value = true
  try {
    if (editingId.value) {
      await behaviorTreeApi.update(editingId.value, payload)
      ElMessage.success('更新成功')
    } else {
      await behaviorTreeApi.create(payload)
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
      `确定删除行为树「${row.name}」吗？`,
      '删除确认',
      { type: 'warning' }
    )
  } catch {
    return
  }
  try {
    await behaviorTreeApi.remove(row.id)
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
      <h3>行为树管理</h3>
      <el-button type="primary" @click="openCreate">新建行为树</el-button>
    </div>

    <el-table v-loading="loading" :data="list" stripe>
      <el-table-column prop="name" label="名称" width="200" />
      <el-table-column prop="description" label="描述" show-overflow-tooltip />
      <el-table-column label="节点数" width="100">
        <template #default="{ row }">
          {{ Array.isArray(row.tree_definition?.nodes) ? row.tree_definition.nodes.length : '-' }}
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
      :title="editingId ? '编辑行为树' : '新建行为树'"
      width="680px"
    >
      <el-form label-width="100px">
        <el-form-item label="名称" required>
          <el-input v-model="form.name" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="树定义" required>
          <el-input
            v-model="form.treeDefinitionText"
            type="textarea"
            :rows="14"
            placeholder="JSON 格式的行为树定义"
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
