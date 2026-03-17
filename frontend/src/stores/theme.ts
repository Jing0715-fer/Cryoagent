import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'

export type ThemeName = 'original' | 'dark' | 'cyberpunk' | 'matrix' | 'persona5' | 'persona4' | 'persona3'

interface Theme {
  name: string
  css: string | null
}

export const useThemeStore = defineStore('theme', () => {
  // State
  const currentTheme = ref<ThemeName>((localStorage.getItem('theme') as ThemeName) || 'original')
  const isAnimating = ref(false)

  // Theme definitions
  const themes: Record<ThemeName, Theme> = {
    original: { name: '原始', css: null },
    dark: { name: '夜间', css: '/static/css/theme-dark.css' },
    cyberpunk: { name: '赛博朋克', css: '/static/css/theme-cyberpunk.css' },
    matrix: { name: '黑客帝国', css: '/static/css/theme-matrix.css' },
    persona5: { name: 'P5', css: '/static/css/theme-persona5.css' },
    persona4: { name: 'P4', css: '/static/css/theme-persona4.css' },
    persona3: { name: 'P3', css: '/static/css/theme-persona3.css' },
  }

  // Getters
  const animatedThemes = computed(() => ['cyberpunk', 'matrix'])
  const isAnimated = computed(() => animatedThemes.value.includes(currentTheme.value))

  // Actions
  function setTheme(themeName: ThemeName) {
    if (!themes[themeName]) {
      console.error('Unknown theme:', themeName)
      return
    }

    currentTheme.value = themeName
    localStorage.setItem('theme', themeName)

    // Apply theme to document
    if (themeName === 'original') {
      document.documentElement.removeAttribute('data-theme')
    } else {
      document.documentElement.setAttribute('data-theme', themeName)
    }

    // Handle animated themes
    isAnimating.value = isAnimated.value

    // Load theme CSS
    loadThemeCSS(themeName)
  }

  function loadThemeCSS(themeName: ThemeName) {
    // Remove existing theme links
    const existingLinks = document.querySelectorAll('link[data-theme-css]')
    existingLinks.forEach(link => link.remove())

    // Add new theme CSS if not original
    const theme = themes[themeName]
    if (theme.css) {
      const link = document.createElement('link')
      link.rel = 'stylesheet'
      link.href = theme.css
      link.setAttribute('data-theme-css', 'true')
      document.head.appendChild(link)
    }
  }

  function toggleTheme() {
    const themeNames = Object.keys(themes) as ThemeName[]
    const currentIndex = themeNames.indexOf(currentTheme.value)
    const nextIndex = (currentIndex + 1) % themeNames.length
    const nextTheme = themeNames[nextIndex]
    if (nextTheme) {
      setTheme(nextTheme)
    }
  }

  // Initialize theme on load
  function init() {
    setTheme(currentTheme.value)
  }

  // Watch for theme changes
  watch(currentTheme, (newTheme) => {
    isAnimating.value = isAnimated.value
  })

  return {
    currentTheme,
    themes,
    isAnimating,
    isAnimated,
    setTheme,
    toggleTheme,
    init,
  }
})
