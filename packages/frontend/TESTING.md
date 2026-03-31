# Frontend Testing Documentation

## Current State

The frontend currently **does not have a test framework configured**. This document outlines the recommended testing approach for the dependent tasks UI component and other frontend features.

## Recommended Test Framework Setup

### Option 1: Vitest + React Testing Library (Recommended)

Vitest is the recommended choice as it integrates seamlessly with Vite (already in use).

**Installation:**
```bash
npm install -D vitest @testing-library/react @testing-library/jest-dom @testing-library/user-event jsdom
```

**Configuration (`vitest.config.ts`):**
```typescript
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
  },
})
```

**Setup file (`src/test/setup.ts`):**
```typescript
import '@testing-library/jest-dom'
```

**Add test script to `package.json`:**
```json
{
  "scripts": {
    "test": "vitest",
    "test:ui": "vitest --ui",
    "test:coverage": "vitest --coverage"
  }
}
```

---

## Dependent Tasks UI Component Tests

Once the test framework is configured, the following test cases should be implemented for the dependent tasks feature in `TaskDetail.tsx`:

### Test File: `src/pages/__tests__/TaskDetail.test.tsx`

#### 1. **Rendering Tests**

```typescript
describe('TaskDetail - Dependent Tasks Display', () => {
  test('should display dependent tasks section when dependencies exist', () => {
    // Mock task with dependent_tasks array
    // Verify section is rendered
    // Verify correct number of dependency cards shown
  });

  test('should not display dependent tasks section when no dependencies', () => {
    // Mock task with empty dependent_tasks array
    // Verify section is not rendered
  });

  test('should display correct dependency information (id, title, status)', () => {
    // Mock task with dependencies
    // Verify each dependency shows correct id, title, and status
  });
});
```

#### 2. **Status Badge Tests**

```typescript
describe('TaskDetail - Dependent Task Status Badges', () => {
  test('should display correct status badge for todo dependency', () => {
    // Mock dependency with status 'todo'
    // Verify badge has correct class and text
  });

  test('should display correct status badge for in_progress dependency', () => {
    // Similar for in_progress status
  });

  test('should display correct status badge for done dependency', () => {
    // Verify 'done' badge shows with correct styling
  });

  test('should display correct status badge for cancelled dependency', () => {
    // Verify 'cancelled' badge shows with correct styling
  });

  test('should apply correct color coding to status badges', () => {
    // Verify CSS classes applied based on status
    // Check that colors match design system
  });
});
```

#### 3. **Interactive Tests**

```typescript
describe('TaskDetail - Dependent Tasks Interaction', () => {
  test('should navigate to dependency when clicking on dependency card', async () => {
    // Mock router
    // Render component with dependencies
    // Click on dependency card
    // Verify navigation to correct task detail page
  });

  test('should show priority badge when dependency has priority set', () => {
    // Mock dependency with priority
    // Verify priority badge renders correctly
  });
});
```

#### 4. **Real-time Update Tests** (Integration with Task #405)

```typescript
describe('TaskDetail - Dependent Tasks Real-time Updates', () => {
  test('should update dependency status when real-time event received', async () => {
    // Mock initial task state
    // Render component
    // Trigger real-time status update event
    // Verify dependency status badge updates without page reload
  });

  test('should refetch task data when dependency status changes', async () => {
    // Mock useApi hook
    // Simulate real-time event
    // Verify refetch was triggered
  });

  test('should handle multiple dependency updates in sequence', async () => {
    // Mock multiple dependencies
    // Send multiple status update events
    // Verify all updates reflected correctly
  });
});
```

#### 5. **Edge Cases**

```typescript
describe('TaskDetail - Dependent Tasks Edge Cases', () => {
  test('should handle task with many dependencies (10+)', () => {
    // Mock task with 15 dependencies
    // Verify all render without performance issues
    // Verify scrolling works if needed
  });

  test('should handle dependency with very long title', () => {
    // Mock dependency with 200-character title
    // Verify text truncation or wrapping works correctly
  });

  test('should show loading state while fetching task data', () => {
    // Mock loading state from useApi
    // Verify loading indicator shown
  });

  test('should show error state if task fetch fails', () => {
    // Mock error state from useApi
    // Verify error message displayed
  });

  test('should handle missing dependency data gracefully', () => {
    // Mock task where depends_on has IDs but dependent_tasks is incomplete
    // Verify no crash, shows fallback UI
  });
});
```

#### 6. **Accessibility Tests**

```typescript
describe('TaskDetail - Dependent Tasks Accessibility', () => {
  test('should have proper ARIA labels for dependency cards', () => {
    // Verify aria-label or role attributes
  });

  test('should be keyboard navigable', async () => {
    // Test tab navigation through dependency cards
    // Verify focus management
  });

  test('should have sufficient color contrast for status badges', () => {
    // Check contrast ratios meet WCAG standards
  });
});
```

---

## Mock Data Utilities

Create a helper file for test data:

### `src/test/mockData.ts`

```typescript
import { TaskDetail, DependentTaskInfo, TaskStatus } from '../api/types';

export const createMockDependentTask = (
  overrides?: Partial<DependentTaskInfo>
): DependentTaskInfo => ({
  id: 1,
  title: 'Test Dependency',
  status: 'todo' as TaskStatus,
  ...overrides,
});

export const createMockTask = (
  overrides?: Partial<TaskDetail>
): TaskDetail => ({
  id: 1,
  team_id: 'team-uuid',
  title: 'Test Task',
  description: 'Test description',
  status: 'todo' as TaskStatus,
  priority: 'medium',
  assignee_id: null,
  dri_id: null,
  depends_on: [],
  dependent_tasks: [],
  repo_ids: [],
  tags: [],
  branch: 'task-1-test-task',
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
  completed_at: null,
  ...overrides,
});
```

---

## Integration Test Considerations

### API Mocking

Use MSW (Mock Service Worker) for API mocking:

```bash
npm install -D msw
```

**Setup MSW handlers:**
```typescript
// src/test/handlers.ts
import { rest } from 'msw';

export const handlers = [
  rest.get('/api/v1/tasks/:taskId', (req, res, ctx) => {
    return res(ctx.json(createMockTask()));
  }),
];
```

### React Query Integration

Mock or provide real React Query client in tests:

```typescript
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const createTestQueryClient = () => new QueryClient({
  defaultOptions: {
    queries: { retry: false },
    mutations: { retry: false },
  },
});

const wrapper = ({ children }) => (
  <QueryClientProvider client={createTestQueryClient()}>
    {children}
  </QueryClientProvider>
);
```

---

## Test Coverage Goals

- **Line Coverage**: > 80%
- **Branch Coverage**: > 75%
- **Function Coverage**: > 80%

### Critical Paths to Test

1. ✅ Dependent tasks section renders when dependencies exist
2. ✅ Status badges display correct colors and text
3. ✅ Navigation to dependency tasks works
4. ✅ Real-time updates trigger UI refresh
5. ✅ Error states display appropriately
6. ✅ Loading states show correctly

---

## Running Tests

Once configured:

```bash
# Run all tests
npm test

# Run with UI
npm run test:ui

# Run with coverage
npm run test:coverage

# Watch mode
npm test -- --watch

# Run specific test file
npm test TaskDetail.test.tsx
```

---

## Next Steps

1. **Install test dependencies** (Vitest, React Testing Library)
2. **Create vitest config** as shown above
3. **Set up test utilities** (mockData.ts, setup.ts)
4. **Implement tests** for TaskDetail component
5. **Add MSW** for API mocking
6. **Configure CI/CD** to run tests on PR
7. **Add coverage reporting** to CI pipeline

---

## Additional Resources

- [Vitest Documentation](https://vitest.dev/)
- [React Testing Library](https://testing-library.com/docs/react-testing-library/intro/)
- [MSW Documentation](https://mswjs.io/)
- [Testing React Query](https://tanstack.com/query/latest/docs/framework/react/guides/testing)
