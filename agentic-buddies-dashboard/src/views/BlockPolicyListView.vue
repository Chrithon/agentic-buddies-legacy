<script setup>
// 拦截策略管理：GET/POST/PUT/DELETE /api/block-policies/
// 字段：policy_id（唯一）、show_name、policy_type、category、risk_level、
//       warning_prompt、alert_enabled
// 约束：(category, risk_level) 唯一
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { blockPolicyApi } from '../api'

const CATEGORY_OPTIONS = [
  { label: '政治', value: 'political' },
  { label: '色情', value: 'sexual' },
  { label: '暴力', value: 'violence' },
  { label: '自杀/自残', value: 'suicide' },
  { label: '自定义', value: 'custom' },
]

const POLICY_TYPE_OPTIONS = [
  { label: '仅报告', value: 'report_only' },
  { label: '警告提示', value: 'warning_prompt' },
  { label: '拦截', value: 'block' },
  { label: '强制拦截', value: 'force_block' },
]

const RISK_LEVEL_OPTIONS = [
  { label: '低风险', value: 1 },
  { label: '中风险', value: 2 },
  { label: '高风险', value: 3 },
]

const list = ref([])
const loading = ref(false)
const filterPolicyType = ref('')
const filterCategory = ref('')
const filterRiskLevel = ref(null)

const dialogVisible = ref(false)
const submitting = ref(false)
const editingId = ref(null)

const form = reactive({
  policy_id: '',
  show_name: '',
  policy_type: 'block',
  category: 'political',
  risk_level: 1,
  warning_prompt: '',
  alert_enabled: false,
})

function labelFor(options, value) {
  return options.find((o) => o.value === value)?.label || value || '-'
}

async function fetchList() {
  loading.value = true
  try {
    const params = {}
    if (filterPolicyType.value) params.policy_type = filterPolicyType.value
    if (filterCategory.value) params.category = filterCategory.value
    if (filterRiskLevel.value) params.risk_level = filterRiskLevel.value
    list.value = await blockPolicyApi.list(params)
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editingId.value = null
  Object.assign(form, {
    policy_id: '',
    show_name: '',
    policy_type: 'block',
    category: 'political',
    risk_level: 1,
    warning_prompt: '',
    alert_enabled: false,
  })
  dialogVisible.value = true
}

function openEdit(row) {
  editingId.value = row.id
  Object.assign(form, {
    policy_id: row.policy_id,
    show_name: row.show_name,
    policy_type: row.policy_type,
    category: row.category,
    risk_level: row.risk_level,
    warning_prompt: row.warning_prompt || '',
    alert_enabled: row.alert_enabled,
  })
  dialogVisible.value = true
}

async function handleSubmit() {
  if (!form.policy_id.trim() || !form.show_name.trim()) {
    ElMessage.warning('标识和显示名称为必填项')
    return
  }
  const payload = {
    policy_id: form.policy_id,
    show_name: form.show_name,
    policy_type: form.policy_type,
    category: form.category,
    risk_level: form.risk_level,
    warning_prompt: form.warning_prompt || null,
    alert_enabled: form.alert_enabled,
  }
  submitting.value = true
  try {
    if (editingId.value) {
      await blockPolicyApi.update(editingId.value, payload)
      ElMessage.success('更新成功')
    } else {
      await blockPolicyApi.create(payload)
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
      `确定删除拦截策略「${row.show_name}」吗？`,
      '删除确认',
      { type: 'warning' }
    )
  } catch {
    return
  }
  try {
    await blockPolicyApi.remove(row.id)
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
      <h3>拦截策略</h3>
      <div class="toolbar-right">
        <el-select v-model="filterPolicyType" placeholder="策略类型" clearable style="width:140px" @change="fetchList">
          <el-option v-for="o in POLICY_TYPE_OPTIONS" :key="o.value" :label="o.label" :value="o.value" />
        </el-select>
        <el-select v-model="filterCategory" placeholder="分类" clearable style="width:110px" @change="fetchList">
          <el-option v-for="o in CATEGORY_OPTIONS" :key="o.value" :label="o.label" :value="o.value" />
        </el-select>
        <el-select v-model="filterRiskLevel" placeholder="风险等级" clearable style="width:120px" @change="fetchList">
          <el-option v-for="o in RISK_LEVEL_OPTIONS" :key="o.value" :label="o.label" :value="o.value" />
        </el-select>
        <el-button type="primary" @click="openCreate">新建策略</el-button>
      </div>
    </div>

    <el-table v-loading="loading" :data="list" stripe>
      <el-table-column prop="policy_id" label="标识" width="160" />
      <el-table-column prop="show_name" label="显示名称" width="200" />
      <el-table-column label="策略类型" width="120">
        <template #default="{ row }">{{ labelFor(POLICY_TYPE_OPTIONS, row.policy_type) }}</template>
      </el-table-column>
      <el-table-column label="分类" width="80">
        <template #default="{ row }">{{ labelFor(CATEGORY_OPTIONS, row.category) }}</template>
      </el-table-column>
      <el-table-column label="风险等级" width="100">
        <template #default="{ row }">{{ labelFor(RISK_LEVEL_OPTIONS, row.risk_level) }}</template>
      </el-table-column>
      <el-table-column label="告警" width="70" align="center">
        <template #default="{ row }">
          <el-tag size="small" :type="row.alert_enabled ? 'warning' : 'info'">
            {{ row.alert_enabled ? '开' : '关' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="150" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button link type="danger" @click="handleDelete(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialogVisible" :title="editingId ? '编辑策略' : '新建策略'" width="600px">
      <el-form label-width="90px">
        <el-form-item label="标识" required>
          <el-input v-model="form.policy_id" placeholder="唯一标识，如 political_high_block" />
        </el-form-item>
        <el-form-item label="显示名称" required>
          <el-input v-model="form.show_name" placeholder="如 政治内容-高风险-拦截" />
        </el-form-item>
        <el-form-item label="策略类型" required>
          <el-select v-model="form.policy_type" style="width:100%">
            <el-option v-for="o in POLICY_TYPE_OPTIONS" :key="o.value" :label="o.label" :value="o.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="分类" required>
          <el-select v-model="form.category" style="width:100%">
            <el-option v-for="o in CATEGORY_OPTIONS" :key="o.value" :label="o.label" :value="o.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="风险等级" required>
          <el-radio-group v-model="form.risk_level">
            <el-radio v-for="o in RISK_LEVEL_OPTIONS" :key="o.value" :value="o.value">{{ o.label }}</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="警告提示">
          <el-input v-model="form.warning_prompt" type="textarea" :rows="3" placeholder="触发时返回给用户的提示文本（可选）" />
        </el-form-item>
        <el-form-item label="触发告警">
          <el-switch v-model="form.alert_enabled" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="handleSubmit">保存</el-button>
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
