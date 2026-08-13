import { useClientLanguage } from '../i18n/useClientLanguage'

export function LanguageSwitcher() {
  const { language, setLanguage } = useClientLanguage()
  return (
    <div className="language-switcher" role="group" aria-label="Language">
      <button type="button" className={language === 'zh-CN' ? 'active' : ''} aria-pressed={language === 'zh-CN'} onClick={() => setLanguage('zh-CN')}>中</button>
      <span aria-hidden="true" />
      <button type="button" className={language === 'en' ? 'active' : ''} aria-pressed={language === 'en'} onClick={() => setLanguage('en')}>EN</button>
    </div>
  )
}
