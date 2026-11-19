<script setup>
// 用户管理（仅管理员）：GET/POST/PUT/DELETE /api/users/
// 功能：列表、创建、启用/禁用、角色调整、重置密码、解锁、删除
// 后端约束：不能修改/删除自己；列表不返回密码哈希
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { userApi } from '../api'
import { useAuthStore } from '../stores/auth'

const authStore = useAuthStore()

const list = ref([])
const loading = ref(false)

const createVisible = ref(false)
const submitting = ref(false)

const createForm = reactive({
  username: '',
  password: '',
  is_admin: false,
})

const LOCKOUT_DURATION_MS = 60 * 60 * 1000
const MAX_FAILED_ATTEMPTS = 3

function isLocked(row) {
  if (row.attmpts < MAX_FAILED_ATTEMPTS || !row.last_failed_attempt) return false
  return Date.now() - new Date(row.last_failed_attempt).getTime() < LOCKOUT_DURATION_MS
}

function lockRemainingMinutes(row) {
  const elapsed = Date.now() - new Date(row.last_failed_attempt).getTime()
  return Math.max(1, Math.ceil((LOCKOUT_DURATION_MS - elapsed) / 60000))
}

const isSelf = computed(() => (row) => row.id === authStore.user?.id)

async function fetchList() {
  loading.value = true
  try {
    list.value = await userApi.list()
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    loading.value = false
  }
}

function openCreate() {
  Object.assign(createForm, { username: '', password: '', is_admin: false })
  createVisible.value = true
}

async function handleCreate() {
  if (!createForm.username.trim() || !createForm.password) {
    ElMessage.warning('用户名和密码为必填项')
    return
  }
  if (createForm.password.length < 8) {
    ElMessage.warning('密码至少 8 位')
    return
  }
  submitting.value = true
  try {
    await userApi.create({ ...createForm })
    ElMessage.success('创建成功')
    createVisible.value = false
    await fetchList()
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    submitting.value = false
  }
}

async function toggleEnabled(row) {
  const action = row.is_enabled ? '禁用' : '启用'
  try {
    await ElMessageBox.confirm(
      `确定${action}用户「${row.username}」吗？${row.is_enabled ? '禁用后该用户将无法登录。' : ''}`,
      `${action}确认`,
      { type: 'warning' }
    )
  } catch {
    return
  }
  try {
    await userApi.update(row.id, { is_enabled: !row.is_enabled })
    ElMessage.success(`已${action}`)
    await fetchList()
  } catch (error) {
    ElMessage.error(error.message)
  }
}

async function toggleAdmin(row) {
  const action = row.is_admin ? '取消管理员' : '设为管理员'
  try {
    await ElMessageBox.confirm(
      `确定将「${row.username}」${action}吗？`,
      '角色变更确认',
      { type: 'warning' }
    )
  } catch {
    return
  }
  try {
    await userApi.update(row.id, { is_admin: !row.is_admin })
    ElMessage.success('已更新角色')
    await fetchList()
  } catch (error) {
    ElMessage.error(error.message)
  }
}

async function handleReset(row) {
  try {
    await ElMessageBox.confirm(
      `确定将「${row.username}」的密码重置为系统默认密码吗？重置后应提醒该用户尽快登录并修改密码。`,
      '重置密码确认',
      { type: 'warning' }
    )
  } catch {
    return
  }
  try {
    await userApi.resetPassword(row.id)
    ElMessage.success('密码已重置为系统默认密码，账户锁定状态已一并解除')
    await fetchList()
  } catch (error) {
    ElMessage.error(error.message)
  }
}

async function handleUnlock(row) {
  try {
    await userApi.unlock(row.id)
    ElMessage.success(`已解锁「${row.username}」`)
    await fetchList()
  } catch (error) {
    ElMessage.error(error.message)
  }
}

async function handleDelete(row) {
  try {
    await ElMessageBox.confirm(
      `确定删除用户「${row.username}」吗？此操作不可恢复。`,
      '删除确认',
      { type: 'warning', confirmButtonText: '删除', confirmButtonClass: 'el-button--danger' }
    )
  } catch {
    return
  }
  try {
    await userApi.remove(row.id)
    ElMessage.success('已删除')
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
      <h3>用户管理</h3>
      <el-button type="primary" @click="openCreate">新建用户</el-button>
    </div>

    <el-table v-loading="loading" :data="list" stripe>
      <el-table-column prop="username" label="用户名" width="200">
        <template #default="{ row }">
          {{ row.username }}
          <el-tag v-if="isSelf(row)" size="small" type="info" class="self-tag">我</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="角色" width="110">
        <template #default="{ row }">
          <el-tag size="small" :type="row.is_admin ? 'primary' : 'info'">
            {{ row.is_admin ? '管理员' : '普通用户' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="140">
        <template #default="{ row }">
          <el-tag v-if="!row.is_enabled" size="small" type="danger">已禁用</el-tag>
          <el-tooltip
            v-else-if="isLocked(row)"
            :content="`剩余约 ${lockRemainingMinutes(row)} 分钟`"
            placement="top"
          >
            <el-tag size="small" type="warning">锁定中</el-tag>
          </el-tooltip>
          <el-tag v-else size="small" type="success">正常</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="失败次数" width="100">
        <template #default="{ row }">{{ row.attmpts }}</template>
      </el-table-column>
      <el-table-column label="操作" min-width="360" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="handleReset(row)">重置密码</el-button>
          <el-button
            v-if="row.attmpts > 0"
            link
            type="warning"
            @click="handleUnlock(row)"
          >
            解锁
          </el-button>
          <el-button
            link
            :type="row.is_enabled ? 'danger' : 'success'"
            :disabled="isSelf(row)"
            @click="toggleEnabled(row)"
          >
            {{ row.is_enabled ? '禁用' : '启用' }}
          </el-button>
          <el-button
            link
            type="primary"
            :disabled="isSelf(row)"
            @click="toggleAdmin(row)"
          >
            {{ row.is_admin ? '取消管理员' : '设为管理员' }}
          </el-button>
          <el-button
            link
            type="danger"
            :disabled="isSelf(row)"
            @click="handleDelete(row)"
          >
            删除
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="createVisible" title="新建用户" width="440px">
      <el-form label-width="90px">
        <el-form-item label="用户名" required>
          <el-input v-model="createForm.username" placeholder="2-50 个字符" />
        </el-form-item>
        <el-form-item label="初始密码" required>
          <el-input
            v-model="createForm.password"
            type="password"
            show-password
            placeholder="至少 8 位"
          />
        </el-form-item>
        <el-form-item label="角色">
          <el-checkbox v-model="createForm.is_admin">设为管理员</el-checkbox>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="handleCreate">
          创建
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

.self-tag {
  margin-left: 6px;
}
</style>
