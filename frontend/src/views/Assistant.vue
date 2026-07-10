<template>
  <div class="assistant-container">
    <!-- 顶部控制栏 -->
    <div class="kg-page-header">
      <el-button size="small" @click="$router.push(`/project/${$route.params.id}/dashboard`)" style="margin-right: 12px;">&larr; 返回</el-button>
      <h2>智能助手</h2>
      <div style="margin-left: auto; display: flex; gap: 12px; align-items: center;">
        <el-select v-model="selectedProjectIds" multiple placeholder="选择图谱（可多选）" style="width: 320px;" size="small">
          <el-option v-for="p in allProjects" :key="p.id" :label="p.name" :value="p.id" />
        </el-select>
        <el-tag v-if="currentProject" type="info" size="small">当前: {{ currentProject.name }}</el-tag>
        <el-popover trigger="click" width="420" @before-enter="loadModelConfig">
          <template #reference>
            <el-button size="small">助手模型: {{ currentModelName }}</el-button>
          </template>
          <div style="padding: 12px;">
            <h4 style="margin: 0 0 12px;">配置智能助手模型</h4>
            <el-form label-width="80px" size="small">
              <el-form-item label="服务商">
                <el-select v-model="modelForm.api_provider" style="width: 100%;">
                  <el-option label="OpenAI" value="OPENAI" />
                  <el-option label="Anthropic" value="ANTHROPIC" />
                  <el-option label="DeepSeek" value="DEEPSEEK" />
                  <el-option label="Qwen" value="QWEN" />
                </el-select>
              </el-form-item>
              <el-form-item label="Base URL">
                <el-input v-model="modelForm.base_url" placeholder="https://api.openai.com/v1" />
              </el-form-item>
              <el-form-item label="API Key">
                <el-input v-model="modelForm.api_key" type="password" show-password placeholder="留空则不更新" />
              </el-form-item>
              <el-form-item label="模型名">
                <el-input v-model="modelForm.model_name" placeholder="gpt-4o / deepseek-chat / qwen-plus" />
              </el-form-item>
            </el-form>
            <el-button type="primary" size="small" @click="saveModelConfig" style="width: 100%; margin-top: 8px;">保存</el-button>
          </div>
        </el-popover>
      </div>
    </div>

    <div class="assistant-body">
      <!-- 左侧: 会话列表 -->
      <div class="session-sidebar">
        <div class="session-header">
          <span>会话列表</span>
          <el-button size="small" type="primary" plain @click="createSession" style="padding: 4px 8px;">+ 新建</el-button>
        </div>
        <div class="session-list">
          <div
            v-for="s in sessions"
            :key="s.id"
            :class="['session-item', { active: currentSessionId === s.id }]"
            @click="switchSession(s.id)"
          >
            <div class="session-item-info">
              <div class="session-title">{{ s.title }}</div>
              <div class="session-meta">{{ formatTime(s.updated_at) }} · {{ s.message_count }}条</div>
            </div>
            <el-dropdown trigger="click" @command="(cmd) => handleSessionCommand(cmd, s)" @click.stop>
              <el-button text size="small" @click.stop>⋯</el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="rename">重命名</el-dropdown-item>
                  <el-dropdown-item command="delete" divided style="color: #f56c6c;">删除</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
          <div v-if="!sessions.length" class="empty-sessions">
            暂无会话<br/>点击"新建"开始
          </div>
        </div>
      </div>

      <!-- 中间: 对话区 -->
      <div class="chat-panel">
        <div ref="msgContainer" class="msg-list">
          <div v-if="!messages.length" class="empty-hint">
            <div style="font-size: 48px; margin-bottom: 16px;">🧠</div>
            <h3>知识图谱智能助手</h3>
            <p style="color: #95a5a6; margin: 8px 0 20px;">基于图谱知识库的推理问答，支持多跳推理和可解释路径</p>
            <div v-if="suggestedQuestions.length" class="suggested-box">
              <p style="color: #7f8c8d; margin-bottom: 8px; font-size: 13px;">试试这些问题：</p>
              <el-button v-for="(q, i) in suggestedQuestions" :key="i" size="small" round style="margin: 4px;" @click="askQuestion(q)">
                {{ q }}
              </el-button>
            </div>
          </div>

          <div v-for="(msg, i) in messages" :key="i" :class="['msg-item', msg.role]">
            <div class="msg-avatar">{{ msg.role === 'user' ? '👤' : '🤖' }}</div>
            <div class="msg-content">
              <div class="msg-text" v-html="formatAnswer(msg.content)"></div>
              <div v-if="msg.reasoning_path && msg.reasoning_path.edges && msg.reasoning_path.edges.length" class="reasoning-toggle">
                <el-button text size="small" @click="toggleReasoning(i)">
                  {{ msg.showReasoning ? '收起推理路径' : '查看推理路径' }}
                  <span style="margin-left: 4px; color: #95a5a6;">({{ msg.reasoning_path.edges.length }} 条关系)</span>
                </el-button>
              </div>
              <div v-if="msg.showReasoning && msg.reasoning_path" class="reasoning-detail">
                <div class="reasoning-section">
                  <strong>识别实体:</strong>
                  <el-tag v-for="e in msg.reasoning_path.entities" :key="e" size="small" style="margin: 2px;">{{ e }}</el-tag>
                </div>
                <div class="reasoning-section">
                  <strong>推理子图 ({{ msg.reasoning_path.nodes.length }} 节点, {{ msg.reasoning_path.edges.length }} 边):</strong>
                  <div class="triple-list">
                    <div v-for="(edge, j) in msg.reasoning_path.edges" :key="j" class="triple-item">
                      <el-tag type="info" size="small">{{ edge.source }}</el-tag>
                      <span style="margin: 0 6px; color: #e67e22;">--{{ edge.label }}--&gt;</span>
                      <el-tag type="success" size="small">{{ edge.target }}</el-tag>
                    </div>
                  </div>
                </div>
                <div v-if="msg.sources && msg.sources.length" class="reasoning-section">
                  <strong>数据来源:</strong>
                  <el-tag v-for="s in msg.sources" :key="s.project_id" type="warning" size="small" style="margin: 2px;">
                    {{ s.project_name }}
                  </el-tag>
                </div>
              </div>
            </div>
          </div>

          <div v-if="loading" class="msg-item assistant">
            <div class="msg-avatar">🤖</div>
            <div class="msg-content">
              <div class="msg-text typing">正在思考中...</div>
            </div>
          </div>
        </div>

        <div class="input-area">
          <el-input
            v-model="inputText"
            type="textarea"
            :rows="2"
            placeholder="输入你的问题，基于知识图谱进行推理问答..."
            @keydown.enter.exact.prevent="askQuestion()"
            resize="none"
          />
          <el-button type="primary" @click="askQuestion()" :loading="loading" :disabled="!inputText.trim()" style="margin-left: 12px; height: 100%;">
            发送
          </el-button>
        </div>
      </div>

      <!-- 右侧: 推理路径可视化 -->
      <div class="graph-panel" v-if="latestReasoning && latestReasoning.edges && latestReasoning.edges.length">
        <div class="graph-panel-header">
          <h4 style="margin: 0;">推理子图可视化</h4>
          <el-button text size="small" @click="clearGraph">关闭</el-button>
        </div>
        <div ref="miniGraphContainer" class="mini-graph"></div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, nextTick, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { assistantApi, llmConfigApi } from '../api'
import api from '../api'
import { useProjectStore } from '../stores'

const route = useRoute()
const router = useRouter()
const projectStore = useProjectStore()
const currentProject = computed(() => projectStore.current)
const projectId = route.params.id

const messages = ref([])
const inputText = ref('')
const loading = ref(false)
const suggestedQuestions = ref([])
const allProjects = ref([])
const selectedProjectIds = ref([])
const msgContainer = ref(null)
const miniGraphContainer = ref(null)
const latestReasoning = ref(null)
const currentModelName = ref('未配置')
const modelForm = reactive({ api_provider: 'OPENAI', base_url: '', api_key: '', model_name: '' })
const modelLoaded = ref(false)

// 会话管理
const sessions = ref([])
const currentSessionId = ref(null)

let miniGraph = null

const COLOR_PALETTE = [
  '#5B8FF9', '#61DDAA', '#F6BD16', '#E8684A', '#6DC8EC',
  '#9270CA', '#FF9D4D', '#269A99', '#FF99C3', '#5AD8A6',
]

onMounted(async () => {
  if (currentProject.value) {
    selectedProjectIds.value = [currentProject.value.id]
  }
  try {
    const res = await api.get('/projects/')
    allProjects.value = res || []
  } catch (e) {}
  try {
    const res = await assistantApi.suggestedQuestions(projectId)
    suggestedQuestions.value = res.questions || []
  } catch (e) {}
  loadModelName()
  await loadSessions()
})

// ==================== 会话管理 ====================

async function loadSessions() {
  try {
    const res = await assistantApi.listSessions(projectId)
    sessions.value = res || []
    // 自动选中最近的会话
    if (sessions.value.length && !currentSessionId.value) {
      await switchSession(sessions.value[0].id)
    }
  } catch (e) {}
}

async function createSession() {
  try {
    const res = await assistantApi.createSession(projectId, '新会话')
    sessions.value.unshift(res)
    currentSessionId.value = res.id
    messages.value = []
    ElMessage.success('新会话已创建')
  } catch (e) {
    ElMessage.error('创建会话失败')
  }
}

async function switchSession(sessionId) {
  currentSessionId.value = sessionId
  messages.value = []
  latestReasoning.value = null
  try {
    const res = await assistantApi.listMessages(projectId, sessionId)
    messages.value = (res || []).map(m => ({
      ...m,
      showReasoning: false,
    }))
    // 如果有最后一条助手消息带 reasoning_path，展示到右侧
    const lastAssistant = [...messages.value].reverse().find(m => m.role === 'assistant' && m.reasoning_path)
    if (lastAssistant) {
      latestReasoning.value = lastAssistant.reasoning_path
    }
    scrollToBottom()
  } catch (e) {
    ElMessage.error('加载消息失败')
  }
}

async function handleSessionCommand(cmd, session) {
  if (cmd === 'rename') {
    try {
      const { value } = await ElMessageBox.prompt('请输入新名称', '重命名会话', {
        inputValue: session.title,
        confirmButtonText: '确定',
        cancelButtonText: '取消',
      })
      if (value && value.trim()) {
        await assistantApi.updateSession(projectId, session.id, value.trim())
        session.title = value.trim()
        ElMessage.success('已重命名')
      }
    } catch (e) {}
  } else if (cmd === 'delete') {
    try {
      await ElMessageBox.confirm('确定删除该会话？所有消息将一并删除。', '删除确认', {
        type: 'warning',
        confirmButtonText: '删除',
        cancelButtonText: '取消',
      })
      await assistantApi.deleteSession(projectId, session.id)
      sessions.value = sessions.value.filter(s => s.id !== session.id)
      if (currentSessionId.value === session.id) {
        currentSessionId.value = null
        messages.value = []
        latestReasoning.value = null
        if (sessions.value.length) {
          await switchSession(sessions.value[0].id)
        }
      }
      ElMessage.success('会话已删除')
    } catch (e) {}
  }
}

function formatTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  const now = new Date()
  const diff = (now - d) / 1000
  if (diff < 60) return '刚刚'
  if (diff < 3600) return Math.floor(diff / 60) + '分钟前'
  if (diff < 86400) return Math.floor(diff / 3600) + '小时前'
  return d.toLocaleDateString('zh-CN')
}

// ==================== 问答 ====================

async function askQuestion(q) {
  const question = q || inputText.value.trim()
  if (!question || loading.value) return
  if (!selectedProjectIds.value.length) {
    ElMessage.warning('请先选择至少一个图谱')
    return
  }

  // 如果没有当前会话，自动创建一个
  if (!currentSessionId.value) {
    try {
      const s = await assistantApi.createSession(projectId, '新会话')
      sessions.value.unshift(s)
      currentSessionId.value = s.id
    } catch (e) {
      ElMessage.error('创建会话失败')
      return
    }
  }

  messages.value.push({ role: 'user', content: question })
  inputText.value = ''
  loading.value = true

  const history = messages.value.slice(-12).map(m => ({
    role: m.role,
    content: m.content,
  }))

  try {
    const res = await assistantApi.chat(projectId, {
      question,
      project_ids: selectedProjectIds.value,
      session_id: currentSessionId.value,
      conversation_history: history,
    })

    messages.value.push({
      role: 'assistant',
      content: res.answer,
      reasoning_path: res.reasoning_path,
      subgraph_stats: res.subgraph_stats,
      sources: res.sources,
      showReasoning: false,
    })
    latestReasoning.value = res.reasoning_path
    await nextTick()
    renderMiniGraph()
    scrollToBottom()
    // 刷新会话列表（更新最后消息时间和数量）
    await loadSessions()
  } catch (e) {
    messages.value.push({
      role: 'assistant',
      content: '抱歉，查询失败: ' + (e.response?.data?.detail || e.message),
    })
  } finally {
    loading.value = false
    scrollToBottom()
  }
}

function toggleReasoning(idx) {
  messages.value[idx].showReasoning = !messages.value[idx].showReasoning
}

function clearGraph() {
  latestReasoning.value = null
  if (miniGraph) {
    miniGraph.destroy()
    miniGraph = null
  }
}

function scrollToBottom() {
  nextTick(() => {
    if (msgContainer.value) {
      msgContainer.value.scrollTop = msgContainer.value.scrollHeight
    }
  })
}

function formatAnswer(text) {
  if (!text) return ''
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/\n\n/g, '</p><p>')
    .replace(/\n/g, '<br>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/`(.+?)`/g, '<code>$1</code>')
}

// ==================== 模型配置 ====================

async function loadModelName() {
  if (modelLoaded.value) return
  try {
    const configs = await llmConfigApi.list(projectId)
    const cfg = (configs || []).find(c => c.pipeline_stage === 'ASSISTANT')
           || (configs || []).find(c => c.pipeline_stage === 'EXTRACTION')
    if (cfg && cfg.model_name) {
      currentModelName.value = cfg.model_name
    }
    modelLoaded.value = true
  } catch (e) {
    modelLoaded.value = true
  }
}

async function loadModelConfig() {
  try {
    const configs = await llmConfigApi.list(projectId)
    const cfg = (configs || []).find(c => c.pipeline_stage === 'ASSISTANT')
    if (cfg) {
      modelForm.api_provider = cfg.api_provider || 'OPENAI'
      modelForm.base_url = cfg.base_url || ''
      modelForm.model_name = cfg.model_name || ''
      if (cfg.model_name) currentModelName.value = cfg.model_name
    } else {
      const ext = (configs || []).find(c => c.pipeline_stage === 'EXTRACTION')
      if (ext) {
        modelForm.api_provider = ext.api_provider || 'OPENAI'
        modelForm.base_url = ext.base_url || ''
        modelForm.model_name = ext.model_name || ''
      }
    }
  } catch (e) {}
}

async function saveModelConfig() {
  try {
    const configs = await llmConfigApi.list(projectId)
    const configList = configs || []
    const existing = configList.find(c => c.pipeline_stage === 'ASSISTANT')
    if (existing) {
      existing.api_provider = modelForm.api_provider
      existing.base_url = modelForm.base_url
      existing.model_name = modelForm.model_name
      if (modelForm.api_key) existing.api_key = modelForm.api_key
    } else {
      configList.push({
        pipeline_stage: 'ASSISTANT',
        api_provider: modelForm.api_provider,
        base_url: modelForm.base_url,
        api_key: modelForm.api_key,
        model_name: modelForm.model_name,
      })
    }
    await llmConfigApi.update(projectId, configList)
    currentModelName.value = modelForm.model_name || '未配置'
    modelLoaded.value = true
    ElMessage.success('模型配置已保存')
  } catch (e) {
    ElMessage.error('保存失败: ' + (e.response?.data?.detail || e.message))
  }
}

// ==================== 推理子图可视化 ====================

function renderMiniGraph() {
  if (!miniGraphContainer.value || !latestReasoning.value) return

  import('@antv/g6').then((G6) => {
    if (miniGraph) {
      miniGraph.destroy()
      miniGraph = null
    }

    const data = latestReasoning.value
    const nodes = data.nodes || []
    const edges = data.edges || []
    if (!nodes.length) return

    const groupColors = {}
    let ci = 0
    nodes.forEach(n => {
      const g = n.group || '_default'
      if (!groupColors[g]) {
        groupColors[g] = COLOR_PALETTE[ci % COLOR_PALETTE.length]
        ci++
      }
    })

    const g6Nodes = nodes.map(n => ({
      id: n.id,
      label: (n.label || n.id).substring(0, 16),
      style: { fill: groupColors[n.group || '_default'], stroke: '#fff', lineWidth: 2 },
      labelCfg: { position: 'bottom', offset: 6, style: { fill: '#333', fontSize: 10 } },
    }))

    const g6Edges = edges.map((e, i) => ({
      id: `e-${i}`,
      source: e.source,
      target: e.target,
      label: e.label || '',
      style: { stroke: '#ccc', lineWidth: 1, endArrow: { path: G6.default.Arrow.triangle(5, 7, 0), fill: '#999' } },
      labelCfg: { autoRotate: true, style: { fill: '#888', fontSize: 9 } },
    }))

    const container = miniGraphContainer.value
    const width = container.clientWidth || 400
    const height = container.clientHeight || 500

    miniGraph = new G6.default.Graph({
      container,
      width,
      height,
      modes: { default: ['drag-canvas', 'zoom-canvas', 'drag-node'] },
      layout: {
        type: 'force',
        preventOverlap: true,
        linkDistance: 120,
        nodeStrength: -200,
        edgeStrength: 0.1,
        alpha: 1,
        alphaDecay: 0.028,
        alphaMin: 0.001,
      },
      defaultNode: { type: 'circle', size: 24 },
      defaultEdge: { type: 'line' },
      fitView: true,
      fitViewPadding: 20,
    })

    miniGraph.data({ nodes: g6Nodes, edges: g6Edges })
    miniGraph.render()
  }).catch(() => {
    ElMessage.warning('G6 加载失败')
  })
}

watch(latestReasoning, () => {
  nextTick(() => renderMiniGraph())
})
</script>

<style scoped>
.assistant-container {
  height: calc(100vh - 0px);
  display: flex;
  flex-direction: column;
}

.assistant-body {
  flex: 1;
  display: flex;
  gap: 12px;
  overflow: hidden;
  padding: 0 0 12px 0;
}

/* 会话侧边栏 */
.session-sidebar {
  width: 220px;
  background: #fff;
  border-radius: 8px;
  box-shadow: 0 2px 12px rgba(0,0,0,0.08);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.session-header {
  padding: 12px 14px;
  border-bottom: 1px solid #eee;
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-weight: 600;
  font-size: 14px;
}

.session-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

.session-item {
  display: flex;
  align-items: center;
  padding: 10px 12px;
  border-radius: 6px;
  cursor: pointer;
  margin-bottom: 4px;
  transition: background 0.2s;
}

.session-item:hover {
  background: #f5f7fa;
}

.session-item.active {
  background: #ecf5ff;
  border-left: 3px solid #409eff;
}

.session-item-info {
  flex: 1;
  min-width: 0;
}

.session-title {
  font-size: 13px;
  color: #303030;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-bottom: 2px;
}

.session-meta {
  font-size: 11px;
  color: #95a5a6;
}

.empty-sessions {
  text-align: center;
  color: #bbb;
  font-size: 13px;
  padding: 40px 12px;
  line-height: 1.8;
}

/* 对话区 */
.chat-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.graph-panel {
  width: 400px;
  background: #fff;
  border-radius: 8px;
  box-shadow: 0 2px 12px rgba(0,0,0,0.08);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.graph-panel-header {
  padding: 12px 16px;
  border-bottom: 1px solid #eee;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.mini-graph {
  flex: 1;
  background: #fafbfc;
}

.msg-list {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
  background: #f5f7fa;
  border-radius: 8px;
}

.empty-hint {
  text-align: center;
  padding: 60px 20px;
}

.suggested-box {
  margin-top: 16px;
  text-align: center;
}

.msg-item {
  display: flex;
  gap: 12px;
  margin-bottom: 20px;
  align-items: flex-start;
}

.msg-item.user {
  flex-direction: row-reverse;
}

.msg-avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  background: #fff;
  flex-shrink: 0;
  box-shadow: 0 1px 4px rgba(0,0,0,0.1);
}

.msg-content {
  max-width: 75%;
}

.msg-item.user .msg-content {
  text-align: right;
}

.msg-text {
  display: inline-block;
  padding: 12px 16px;
  border-radius: 12px;
  text-align: left;
  line-height: 1.6;
  font-size: 14px;
}

.msg-item.user .msg-text {
  background: #409eff;
  color: #fff;
}

.msg-item.assistant .msg-text {
  background: #fff;
  color: #333;
  box-shadow: 0 1px 4px rgba(0,0,0,0.06);
}

.msg-text.typing {
  color: #95a5a6;
  font-style: italic;
}

.reasoning-toggle {
  margin-top: 6px;
}

.reasoning-detail {
  margin-top: 8px;
  padding: 12px;
  background: #f8f9fb;
  border-radius: 8px;
  border: 1px solid #e8e8e8;
  text-align: left;
}

.reasoning-section {
  margin-bottom: 10px;
  font-size: 13px;
}

.triple-list {
  margin-top: 6px;
  max-height: 200px;
  overflow-y: auto;
}

.triple-item {
  padding: 4px 0;
  font-size: 12px;
}

.input-area {
  margin-top: 12px;
  display: flex;
  gap: 0;
  align-items: stretch;
}
</style>
