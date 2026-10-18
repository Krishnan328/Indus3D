import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{js,jsx}'],
    extends: [
      js.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
      parserOptions: {
        ecmaVersion: 'latest',
        ecmaFeatures: { jsx: true },
        sourceType: 'module',
      },
    },
    rules: {
      'no-unused-vars': ['error', { varsIgnorePattern: '^[A-Z_]' }],
      // These draft editors intentionally synchronize API-loaded settings into
      // editable local state. The React Compiler advisory treats that common
      // form pattern as a cascading-render risk even though each sync is
      // driven by an asynchronous API refresh.
      'react-hooks/set-state-in-effect': 'off',
      // Relative timestamps are intentionally calculated while rendering.
      'react-hooks/purity': 'off',
    },
  },
])
