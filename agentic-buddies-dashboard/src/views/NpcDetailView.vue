<script setup>
// NPC 详情：GET /api/npcs/:id
// MCP 绑定管理：GET /api/npcs/:id/mcp、POST /api/npcs/:id/mcp {mcp_id}、DELETE /api/npcs/:id/mcp/:mcpId
// 行为树绑定管理：GET /api/npcs/:id/behavior-trees、POST /api/npcs/:id/behavior-trees {behavior_tree_id}、
//               DELETE /api/npcs/:id/behavior-trees/:treeId
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { npcApi, mcpApi, worldApi, behaviorTreeApi } from '../api'

const route = useRoute()
const router = useRouter()
const npcId = Number(route.params.id)

const npc = ref(null)
const worlds = ref([])
const boundMcps = ref([])
const allMcps = ref([])
const loading = ref(false)
const bindLoading = ref(false)
const selectedMcpId = ref(null)

const boundTrees = ref([])
const allTrees = ref([])
const treeBindLoading = ref(false)
const selectedTreeId = ref(null)

const worldName = computed(() => {
  if (!npc.value?.related_world) return '-'
  const w = worlds.value.find((item) => item.id === npc.value.related_world)
  return w ? w.name : `#${npc.value.related_world}`
})

// 尚未绑定到该 NPC 的 MCP（绑定下拉候选）
const unboundMcps = computed(() => {
  const boundIds = new Set(boundMcps.value.map((m) => m.id))
  return allMcps.value.filter((m) => !boundIds.has(m.id))
})

// 尚未绑定到该 NPC 的行为树（绑定下拉候选）
const unboundTrees = computed(() => {
  const boundIds = new Set(boundTrees.value.map((t) => t.id))
  return allTrees.value.filter((t) => !boundIds.has(t.id))
})

async function fetchAll() {
  loading.value = true
  try {
    const [npcData, bound, all, worldList, trees, allTreeList] = await Promise.all([
      npcApi.detail(npcId),
      npcApi.listMcp(npcId),
      mcpApi.list(),
      worldApi.list(),
      npcApi.listBehaviorTrees(npcId),
      behaviorTreeApi.list(),
    ])
    npc.value = npcData
    boundMcps.value = bound
    allMcps.value = all
    worlds.value = worldList
    boundTrees.value = trees
    allTrees.value = allTreeList
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    loading.value = false
  }
}

async function handleBind() {
  if (!selectedMcpId.value) return
  bindLoading.value = true
  try {
    await npcApi.bindMcp(npcId, selectedMcpId.value)
    ElMessage.success('绑定成功')
    selectedMcpId.value = null
    boundMcps.value = await npcApi.listMcp(npcId)
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    bindLoading.value = false
  }
}

async function handleUnbind(row) {
  try {
    await ElMessageBox.confirm(
      `确定解绑 MCP「${row.name}」吗？`,
      '解绑确认',
      { type: 'warning' }
    )
  } catch {
    return
  }
  try {
    await npcApi.unbindMcp(npcId, row.id)
    ElMessage.success('已解绑')
    boundMcps.value = await npcApi.listMcp(npcId)
  } catch (error) {
    ElMessage.error(error.message)
  }
}

async function handleBindTree() {
  if (!selectedTreeId.value) return
  treeBindLoading.value = true
  try {
    await npcApi.bindBehaviorTree(npcId, selectedTreeId.value)
    ElMessage.success('行为树绑定成功')
    selectedTreeId.value = null
    boundTrees.value = await npcApi.listBehaviorTrees(npcId)
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    treeBindLoading.value = false
  }
}

async function handleUnbindTree(row) {
  try {
    await ElMessageBox.confirm(
      `确定解绑行为树「${row.name}」吗？`,
      '解绑确认',
      { type: 'warning' }
    )
  } catch {
    return
  }
  try {
    await npcApi.unbindBehaviorTree(npcId, row.id)
    ElMessage.success('已解绑')
    boundTrees.value = await npcApi.listBehaviorTrees(npcId)
  } catch (error) {
    ElMessage.error(error.message)
  }
}

onMounted(fetchAll)
</script>

<template>
  <div v-loading="loading">
    <el-card v-if="npc" class="info-card">
      <div class="toolbar">
        <h3>{{ npc.name }}</h3>
        <el-button @click="router.push({ name: 'npcs' })">返回列表</el-button>
      </div>
      <el-descriptions :column="2" border>
        <el-descriptions-item label="状态">
          <el-tag size="small" :type="npc.is_enabled ? 'success' : 'info'">
            {{ npc.is_enabled ? '启用' : '停用' }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="所属世界观">{{ worldName }}</el-descriptions-item>
        <el-descriptions-item label="简单任务模型">
          {{ npc.model_config?.simple_task_model || '-' }}
        </el-descriptions-item>
        <el-descriptions-item label="复杂任务模型">
          {{ npc.model_config?.complex_task_model || '-' }}
        </el-descriptions-item>
        <el-descriptions-item label="角色 Prompt" :span="2">
          <pre class="prompt">{{ npc.character_prompt || '（未设置）' }}</pre>
        </el-descriptions-item>
      </el-descriptions>
    </el-card>

    <el-card>
      <div class="toolbar">
        <h3>绑定的 MCP 服务</h3>
        <div class="bind-bar">
          <el-select
            v-model="selectedMcpId"
            placeholder="选择要绑定的 MCP"
            style="width: 240px"
          >
            <el-option
              v-for="m in unboundMcps"
              :key="m.id"
              :label="`${m.name}（${m.type}）`"
              :value="m.id"
            />
          </el-select>
          <el-button
            type="primary"
            :disabled="!selectedMcpId"
            :loading="bindLoading"
            @click="handleBind"
          >
            绑定
          </el-button>
        </div>
      </div>

      <el-table :data="boundMcps" stripe>
        <el-table-column prop="name" label="名称" width="200" />
        <el-table-column prop="type" label="类型" width="150">
          <template #default="{ row }">
            <el-tag size="small">{{ row.type }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="url" label="URL" show-overflow-tooltip />
        <el-table-column prop="timeout" label="超时(秒)" width="100" />
        <el-table-column label="操作" width="100" fixed="right">
          <template #default="{ row }">
            <el-button link type="danger" @click="handleUnbind(row)">解绑</el-button>
          </template>
        </el-table-column>
        <template #empty>暂未绑定任何 MCP 服务</template>
      </el-table>
    </el-card>

    <el-card>
      <div class="toolbar">
        <h3>绑定的行为树</h3>
        <div class="bind-bar">
          <el-select
            v-model="selectedTreeId"
            placeholder="选择要绑定的行为树"
            style="width: 240px"
          >
            <el-option
              v-for="t in unboundTrees"
              :key="t.id"
              :label="t.name"
              :value="t.id"
            />
          </el-select>
          <el-button
            type="primary"
            :disabled="!selectedTreeId"
            :loading="treeBindLoading"
            @click="handleBindTree"
          >
            绑定
          </el-button>
        </div>
      </div>

      <el-table :data="boundTrees" stripe>
        <el-table-column prop="name" label="名称" width="240" />
        <el-table-column prop="description" label="描述" show-overflow-tooltip />
        <el-table-column label="操作" width="100" fixed="right">
          <template #default="{ row }">
            <el-button link type="danger" @click="handleUnbindTree(row)">解绑</el-button>
          </template>
        </el-table-column>
        <template #empty>暂未绑定任何行为树</template>
      </el-table>
    </el-card>
  </div>
</template>

<style scoped>
.info-card {
  margin-bottom: 16px;
}

.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.toolbar h3 {
  margin: 0;
}

.bind-bar {
  display: flex;
  gap: 12px;
}

.prompt {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-all;
  font-family: monospace;
  font-size: 13px;
}
</style>
