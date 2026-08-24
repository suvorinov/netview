/** Конфигурация Tailwind для NetView.
 *
 * Зеркало прежнего inline-конфига из base.html (Play CDN).
 * Пересборка CSS: make css
 */
module.exports = {
  // Тёмная тема по классу на <html> (переключатель темы в шапке)
  darkMode: 'class',
  content: ['./app/templates/**/*.html', './app/static/js/**/*.js'],
  theme: {
    extend: {
      colors: {
        sidebar: '#1e293b',
        sidebarHover: '#334155',
      },
    },
  },
  plugins: [],
};
