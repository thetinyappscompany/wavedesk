// @ts-check
import js from '@eslint/js';
import tseslint from 'typescript-eslint';
import prettier from 'eslint-config-prettier';

export default tseslint.config(
  { ignores: ['dist/**', 'node_modules/**'] },
  js.configs.recommended,
  ...tseslint.configs.strictTypeChecked,
  {
    languageOptions: {
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
    rules: {
      '@typescript-eslint/no-explicit-any': 'error',
      '@typescript-eslint/explicit-module-boundary-types': 'error',
    },
  },
  {
    files: ['test/**/*.ts'],
    rules: {
      // expect(() => fnReturningVoid()) is idiomatic in vitest assertions
      '@typescript-eslint/no-confusing-void-expression': 'off',
      // arr[0]!.field after a length assertion is idiomatic in tests
      '@typescript-eslint/no-non-null-assertion': 'off',
    },
  },
  prettier,
);
