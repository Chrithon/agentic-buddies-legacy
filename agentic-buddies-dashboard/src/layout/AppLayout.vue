<script setup>
import { computed, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { authApi } from '../api'
import { FontAwesomeIcon } from '@fortawesome/vue-fontawesome'
import {
  faUser,
  faEarthAsia,
  faDiagramProject,
  faMicrochip,
  faPlug,
  faShieldHalved,
  faBan,
  faComments,
  faUsersGear,
} from '@fortawesome/free-solid-svg-icons'
import { useAuthStore } from '../stores/auth'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

const menuItems = [
  { index: '/npcs', title: 'NPC管理', icon: faUser },
  { index: '/worlds', title: '世界观管理', icon: faEarthAsia },
  { index: '/behavior-trees', title: '行为树管理', icon: faDiagramProject },
  { index: '/llm-providers', title: 'LLM 提供商', icon: faMicrochip },
  { index: '/mcp', title: 'MCP 服务', icon: faPlug },
  { index: '/word-list', title: '敏感词表', icon: faShieldHalved },
  { index: '/block-policies', title: '拦截策略', icon: faBan },
  { index: '/logs', title: '对话日志', icon: faComments },
  { index: '/users', title: '用户管理', icon: faUsersGear, admin: true },
]

// 用户管理菜单仅管理员可见
const visibleMenuItems = computed(() =>
  menuItems.filter((item) => !item.admin || authStore.user?.is_admin)
)

function handleLogout() {
  authStore.logout()
  router.push({ name: 'login' })
}

// ---------- 本人修改密码 ----------
const passwordVisible = ref(false)
const passwordSubmitting = ref(false)
const passwordForm = reactive({
  old_password: '',
  new_password: '',
  confirm_password: '',
})

function openChangePassword() {
  Object.assign(passwordForm, {
    old_password: '',
    new_password: '',
    confirm_password: '',
  })
  passwordVisible.value = true
}

async function handleChangePassword() {
  if (!passwordForm.old_password || !passwordForm.new_password) {
    ElMessage.warning('请填写完整')
    return
  }
  if (passwordForm.new_password.length < 8) {
    ElMessage.warning('新密码至少 8 位')
    return
  }
  if (passwordForm.new_password !== passwordForm.confirm_password) {
    ElMessage.error('两次输入的新密码不一致')
    return
  }
  passwordSubmitting.value = true
  try {
    await authApi.changePassword({ ...passwordForm })
    ElMessage.success('密码修改成功')
    passwordVisible.value = false
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    passwordSubmitting.value = false
  }
}

function handleUserCommand(command) {
  if (command === 'logout') handleLogout()
  else if (command === 'change-password') openChangePassword()
}
</script>

<template>
  <el-container class="app-layout">
    <el-aside width="220px" class="aside">
      <div class="logo">Agentic Buddies</div>
      <el-menu
        :default-active="route.path"
        router
        background-color="#001529"
        text-color="#a6adb4"
        active-text-color="#ffffff"
      >
        <el-menu-item
          v-for="item in visibleMenuItems"
          :key="item.index"
          :index="item.index"
        >
          <el-icon><FontAwesomeIcon :icon="item.icon" /></el-icon>
          <template #title>{{ item.title }}</template>
        </el-menu-item>
      </el-menu>
    </el-aside>

    <el-container>
      <el-header class="header">
        <span class="page-title">{{ route.meta.title }}</span>
        <el-dropdown @command="handleUserCommand">
          <span class="user-info">
            {{ authStore.user?.username || '用户' }}
          </span>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="change-password">修改密码</el-dropdown-item>
              <el-dropdown-item command="logout" divided>退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </el-header>

      <el-main>
        <router-view />
      </el-main>
    </el-container>

    <el-dialog v-model="passwordVisible" title="修改密码" width="440px">
      <el-form label-width="90px">
        <el-form-item label="旧密码" required>
          <el-input
            v-model="passwordForm.old_password"
            type="password"
            show-password
          />
        </el-form-item>
        <el-form-item label="新密码" required>
          <el-input
            v-model="passwordForm.new_password"
            type="password"
            show-password
            placeholder="至少 8 位"
          />
        </el-form-item>
        <el-form-item label="确认密码" required>
          <el-input
            v-model="passwordForm.confirm_password"
            type="password"
            show-password
            placeholder="再次输入新密码"
            @keyup.enter="handleChangePassword"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="passwordVisible = false">取消</el-button>
        <el-button
          type="primary"
          :loading="passwordSubmitting"
          @click="handleChangePassword"
        >
          确认修改
        </el-button>
      </template>
    </el-dialog>
  </el-container>
</template>

<style scoped>
.app-layout {
  height: 100vh;
}

.aside {
  background-color: #001529;
}

.logo {
  height: 60px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: bold;
  font-size: 16px;
  color: #ffffff;
}

.el-menu {
  border-right: none;
}

/* 菜单项悬停与选中态（深色主题） */
.el-menu :deep(.el-menu-item:hover) {
  background-color: #000c17;
}

.el-menu :deep(.el-menu-item.is-active) {
  background-color: var(--el-color-primary);
}

.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid var(--el-border-color);
}

.page-title {
  font-size: 16px;
  font-weight: 600;
}

.user-info {
  cursor: pointer;
}
</style>
