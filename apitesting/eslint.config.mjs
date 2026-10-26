import js from '@eslint/js';
import tseslint from 'typescript-eslint';

export default tseslint.config(
  { ignores: ['node_modules', 'reports', 'test-results', 'playwright-report', 'mock/**'] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ['**/*.ts'],
    rules: {
      'no-restricted-syntax': [
        'error',
        { selector: "CallExpression[callee.object.name='test'][callee.property.name='only']", message: 'Do not commit test.only.' },
        { selector: "CallExpression[callee.property.name='waitForTimeout']", message: 'Avoid fixed waits in API tests.' },
      ],
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_' }],
    },
  },
);
