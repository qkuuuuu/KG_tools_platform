<template>
  <div>
    <div class="kg-page-header">
      <h2>多项目图谱融合</h2>
    </div>

    <div class="kg-card">
      <h3 style="margin-bottom: 16px;">选择项目</h3>
      <el-checkbox-group v-model="selectedProjects">
        <el-checkbox v-for="p in projects" :key="p.id" :label="p.id" style="margin-bottom: 8px;">
          {{ p.name }}
        </el-checkbox>
      </el-checkbox-group>
      <div style="margin-top: 12px;">
        <el-button type="primary" @click="loadGraph" :loading="loading" :disabled="selectedProjects.length < 1">
          融合图谱
        </el-button>
        <el-button @click="showSharedOnly = !showSharedOnly" :disabled="!graphData.nodes.length">
          {{ showSharedOnly ? '显示全部' : '只看共享节点' }}
        </el-button>
      </div>
    </div>

    <!-- 统计 -->
    <div v-if="graphData.nodes.length" class="kg-stat-row">
      <div class="kg-stat-item">
        <div class="kg-stat-value">{{ graphData.nodes.length }}</div>
        <div class="kg-stat-label">节点</div>
      </div>
      <div class="kg-stat-item">
        <div class="kg-stat-value" style="color: #3498db;">{{ graphData.edges.length }}</div>
        <div class="kg-stat-label">关系</div>
      </div>
      <div class="kg-stat-item">
        <div class="kg-stat-value" style="color: #e74c3c;">{{ graphData.shared?.length || 0 }}</div>
        <div class="kg-stat-label">共享节点</div>
      </div>
    </div>

    <!-- 图谱 -->
    <div v-if="graphData.nodes.length" class="kg-card">
      <div ref="graphContainer" style="width: 100%; height: 600px;"></div>
    </div>

    <!-- 共享节点列表 -->
    <div v-if="graphData.shared?.length" class="kg-card">
      <h3 style="margin-bottom: 16px;">跨项目共享实体</h3>
      <el-table :data="graphData.shared" stripe style="width: 100%">
        <el-table-column prop="label" label="实体名" />
        <el-table-column label="出现项目" min-width="200">
          <template #default="{ row }">
            <el-tag v-for="p in row.projects" :key="p" size="small" style="margin-right: 4px;">{{ p }}</el-tag>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, nextTick, watch } from 'vue'
import { ElMessage } from 'element-plus'
import api from '../api'

const projects = ref([])
const selectedProjects = ref([])
const graphData = ref({ nodes: [], edges: [], shared: [] })
const loading = ref(false)
const showSharedOnly = ref(false)
const graphContainer = ref(null)
let graph = null

onMounted(async () => {
  try {
    projects.value = await api.get('/projects/')
  } catch (e) {
    ElMessage.error('加载项目列表失败')
  }
})

async function loadGraph() {
  if (!selectedProjects.value.length) return
  loading.value = true
  try {
    const ids = selectedProjects.value.join(',')
    graphData.value = await api.get(`/export/multi-project-graph?project_ids=${ids}`)
    await nextTick()
    renderGraph()
  } catch (e) {
    ElMessage.error('加载图谱失败')
  } finally {
    loading.value = false
  }
}

function renderGraph() {
  if (!graphContainer.value) return
  // 动态加载 G6
  import('@antv/g6').then((G6) => {
    if (graph) graph.destroy()
    
    let nodes = graphData.value.nodes
    let edges = graphData.value.edges
    
    if (showSharedOnly.value) {
      const sharedIds = new Set(graphData.value.shared.map(n => n.id))
      nodes = nodes.filter(n => sharedIds.has(n.id))
      edges = edges.filter(e => sharedIds.has(e.source) && sharedIds.has(e.target))
    }

    const colorMap = {}
    const palette = ['#5B8FF9', '#5AD8A6', '#5D7092', '#F6BD16', '#E8684A', '#6DC8EC', '#9270CA', '#FF9D4D']
    let colorIdx = 0
    
    nodes = nodes.map(n => {
      if (!colorMap[n.group]) {
        colorMap[n.group] = palette[colorIdx % palette.length]
        colorIdx++
      }
      return {
        ...n,
        style: {
          fill: colorMap[n.group],
          stroke: '#fff',
          lineWidth: 2,
        },
        size: 30 + Math.min(n.label.length * 2, 20),
      }
    })
    
    edges = edges.map((e, i) => ({
      ...e,
      id: `edge-${i}`,
      style: {
        stroke: '#ccc',
        lineWidth: 1,
        endArrow: { path: G6.default.Arrow.triangle(6, 8, 0), fill: '#ccc' },
      },
    }))

    graph = new G6.default.Graph({
      container: graphContainer.value,
      width: graphContainer.value.offsetWidth,
      height: 600,
      modes: {
        default: ['drag-canvas', 'zoom-canvas', 'drag-node'],
      },
      layout: {
        type: 'force',
        preventOverlap: true,
        nodeStrength: -50,
        edgeStrength: 0.1,
        collideStrength: 0.8,
        alpha: 0.3,
      },
      defaultNode: {
        type: 'circle',
        labelCfg: { position: 'bottom', style: { fontSize: 10 } },
      },
      defaultEdge: {
        type: 'quadratic',
        labelCfg: { autoRotate: true, style: { fontSize: 9, fill: '#999' } },
      },
      nodeStateStyles: {
        hover: { shadowBlur: 10, shadowColor: '#333' },
      },
    })

    graph.data({ nodes, edges })
    graph.render()
  }).catch(() => {
    ElMessage.warning('G6 加载失败，请确认已安装 @antv/g6')
  })
}

watch(showSharedOnly, () => {
  if (graphData.value.nodes.length) renderGraph()
})
</script>
