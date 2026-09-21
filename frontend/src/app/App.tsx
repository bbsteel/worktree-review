import { RouterProvider } from 'react-router'
import { router } from './router.tsx'
import { ThemeProvider } from './ThemeProvider.tsx'
import { I18nProvider } from '../i18n.tsx'

export function App() {
  return (
    <I18nProvider>
      <ThemeProvider>
        <RouterProvider router={router} />
      </ThemeProvider>
    </I18nProvider>
  )
}
