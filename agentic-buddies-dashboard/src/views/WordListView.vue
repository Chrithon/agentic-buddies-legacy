<script setup>
// 敏感词表管理：GET/POST/PUT/DELETE /api/word-list/
// 字段：id、word（全局唯一）、list_type(blacklist/whitelist)、
//       category(political/sexual/violence/custom，仅黑名单适用)、
//       risk_level(1=低风险/2=中风险/3=高风险，仅黑名单适用)
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { wordListApi } from '../api'

const CATEGORY_OPTIONS = [
  { label: '政治', value: 'political' },
  { label: '色情', value: 'sexual' },
  { label: '暴力', value: 'violence' },
  { label: '自杀/自残', value: 'suicide' },
  { label: '自定义', value: 'custom' },
]

const RISK_LEVEL_OPTIONS = [
  { label: '低风险', value: 1 },
  { label: '中风险', value: 2 },
  { label: '高风险', value: 3 },
]

const list = ref([])
const loading = ref(false)
const filterType = ref('')
const filterCategory = ref('')
const filterRiskLevel = ref(null)

const dialogVisible = ref(false)
const submitting = ref(false)
const editingId = ref(null)

const form = reactive({
  word: '',
  list_type: 'blacklist',
  category: null,
  risk_level: null,
})

// category / risk_level 仅黑名单适用；切换为白名单时强制清空
const blacklistOnlyDisabled = computed(() => form.list_type === 'whitelist')

function categoryLabel(value) {
  return CATEGORY_OPTIONS.find((o) => o.value === value)?.label || value || '-'
}

function riskLevelLabel(value) {
  return RISK_LEVEL_OPTIONS.find((o) => o.value === value)?.label || '-'
}

async function fetchList() {
  loading.value = true
  try {
    const params = {}
    if (filterType.value) params.list_type = filterType.value
    if (filterCategory.value) params.category = filterCategory.value
    if (filterRiskLevel.value) params.risk_level = filterRiskLevel.value
    list.value = await wordListApi.list(params)
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editingId.value = null
  Object.assign(form, { word: '', list_type: 'blacklist', category: null, risk_level: null })
  dialogVisible.value = true
}

function openEdit(row) {
  editingId.value = row.id
  Object.assign(form, {
    word: row.word,
    list_type: row.list_type,
    category: row.category,
    risk_level: row.risk_level,
  })
  dialogVisible.value = true
}

async function handleSubmit() {
  if (!form.word.trim()) {
    ElMessage.warning('词条为必填项')
    return
  }
  const payload = {
    word: form.word,
    list_type: form.list_type,
    category: form.list_type === 'blacklist' ? form.category : null,
    risk_level: form.list_type === 'blacklist' ? form.risk_level : null,
  }
  submitting.value = true
  try {
    if (editingId.value) {
      await wordListApi.update(editingId.value, payload)
      ElMessage.success('更新成功')
    } else {
      await wordListApi.create(payload)
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
      `确定删除词条「${row.word}」吗？`,
      '删除确认',
      { type: 'warning' }
    )
  } catch {
    return
  }
  try {
    await wordListApi.remove(row.id)
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
      <h3>敏感词表</h3>
      <div class="toolbar-right">
        <el-select
          v-model="filterType"
          placeholder="类型"
          clearable
          style="width: 130px"
          @change="fetchList"
        >
          <el-option label="黑名单" value="blacklist" />
          <el-option label="白名单" value="whitelist" />
        </el-select>
        <el-select
          v-model="filterCategory"
          placeholder="分类"
          clearable
          style="width: 130px"
          @change="fetchList"
        >
          <el-option
            v-for="o in CATEGORY_OPTIONS"
            :key="o.value"
            :label="o.label"
            :value="o.value"
          />
        </el-select>
        <el-select
          v-model="filterRiskLevel"
          placeholder="风险等级"
          clearable
          style="width: 130px"
          @change="fetchList"
        >
          <el-option
            v-for="o in RISK_LEVEL_OPTIONS"
            :key="o.value"
            :label="o.label"
            :value="o.value"
          />
        </el-select>
        <el-button type="primary" @click="openCreate">新建词条</el-button>
      </div>
    </div>

    <el-table v-loading="loading" :data="list" stripe>
      <el-table-column prop="word" label="词条" />
      <el-table-column label="类型" width="120">
        <template #default="{ row }">
          <el-tag size="small" :type="row.list_type === 'blacklist' ? 'danger' : 'success'">
            {{ row.list_type === 'blacklist' ? '黑名单' : '白名单' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="分类" width="120">
        <template #default="{ row }">{{ categoryLabel(row.category) }}</template>
      </el-table-column>
      <el-table-column label="风险等级" width="110">
        <template #default="{ row }">{{ riskLevelLabel(row.risk_level) }}</template>
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
      :title="editingId ? '编辑词条' : '新建词条'"
      width="480px"
    >
      <el-form label-width="80px">
        <el-form-item label="词条" required>
          <el-input v-model="form.word" />
        </el-form-item>
        <el-form-item label="类型" required>
          <el-radio-group
            v-model="form.list_type"
            @change="blacklistOnlyDisabled && (form.category = null, form.risk_level = null)"
          >
            <el-radio value="blacklist">黑名单</el-radio>
            <el-radio value="whitelist">白名单</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="分类">
          <el-select
            v-model="form.category"
            clearable
            :disabled="blacklistOnlyDisabled"
            placeholder="仅黑名单适用"
            style="width: 100%"
          >
            <el-option
              v-for="o in CATEGORY_OPTIONS"
              :key="o.value"
              :label="o.label"
              :value="o.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="风险等级">
          <el-select
            v-model="form.risk_level"
            clearable
            :disabled="blacklistOnlyDisabled"
            placeholder="仅黑名单适用"
            style="width: 100%"
          >
            <el-option
              v-for="o in RISK_LEVEL_OPTIONS"
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
