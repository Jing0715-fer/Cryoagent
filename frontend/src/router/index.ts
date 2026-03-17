import { createRouter, createWebHistory } from 'vue-router'
import HomeView from '../views/HomeView.vue'
import LiteratureView from '../views/LiteratureView.vue'
import LiteratureDetailView from '../views/LiteratureDetailView.vue'
import StructuresView from '../views/StructuresView.vue'
import StructureDetailView from '../views/StructureDetailView.vue'
import QAView from '../views/QAView.vue'
import AlignmentView from '../views/AlignmentView.vue'
import KnowledgeGraphView from '../views/KnowledgeGraphView.vue'
import SettingsView from '../views/SettingsView.vue'
import FeishuConfigView from '../views/FeishuConfigView.vue'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      name: 'home',
      component: HomeView,
      meta: { title: '首页' },
    },
    {
      path: '/literature',
      name: 'literature',
      component: LiteratureView,
      meta: { title: '文献管理' },
    },
    {
      path: '/literature/:id',
      name: 'literature-detail',
      component: LiteratureDetailView,
      props: true,
      meta: { title: '文献详情' },
    },
    {
      path: '/structures',
      name: 'structures',
      component: StructuresView,
      meta: { title: '结构管理' },
    },
    {
      path: '/structures/:id',
      name: 'structure-detail',
      component: StructureDetailView,
      props: true,
      meta: { title: '结构详情' },
    },
    {
      path: '/qa',
      name: 'qa',
      component: QAView,
      meta: { title: '智能问答' },
    },
    {
      path: '/alignment',
      name: 'alignment',
      component: AlignmentView,
      meta: { title: '序列比对' },
    },
    {
      path: '/knowledge-graph',
      name: 'knowledge-graph',
      component: KnowledgeGraphView,
      meta: { title: '知识图谱' },
    },
    {
      path: '/settings',
      name: 'settings',
      component: SettingsView,
      meta: { title: '系统设置' },
    },
    {
      path: '/feishu-config',
      name: 'feishu-config',
      component: FeishuConfigView,
      meta: { title: '飞书配置' },
    },
    {
      path: '/:pathMatch(.*)*',
      name: 'not-found',
      component: () => import('../views/NotFoundView.vue'),
      meta: { title: '页面未找到' },
    },
  ],
})

// Navigation guard to set page title
router.beforeEach((to, from, next) => {
  const title = to.meta.title as string
  if (title) {
    document.title = `${title} - CryoAgent Pro`
  } else {
    document.title = 'CryoAgent Pro'
  }
  next()
})

export default router
