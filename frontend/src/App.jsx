import { useEffect, useRef, useState } from 'react'

const API = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'
const TOKEN_KEY = 'kca_access_token'

function getToken() { try { return localStorage.getItem(TOKEN_KEY) } catch { return null } }
function storeToken(token) { try { token ? localStorage.setItem(TOKEN_KEY, token) : localStorage.removeItem(TOKEN_KEY) } catch { /* private mode */ } }

let handleUnauthorized = () => {}

function detailMessage(data) {
  const detail = data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map((item) => item.msg).join(', ')
  return '요청을 처리하지 못했습니다.'
}

async function request(path, options = {}) {
  const token = getToken()
  const headers = {...(options.headers || {})}
  if (token) headers.Authorization = 'Bearer ' + token
  const response = await fetch(API + path, {...options, headers})
  if (response.status === 401) {
    storeToken(null)
    handleUnauthorized()
    throw new Error('로그인이 필요합니다.')
  }
  const data = await response.json()
  if (!response.ok) throw new Error(detailMessage(data))
  return data
}

function App() {
  const [currentUser, setCurrentUser] = useState(null)
  const [sessionChecked, setSessionChecked] = useState(false)
  const [authMode, setAuthMode] = useState('login')
  const [view, setView] = useState('dashboard')
  const [subjects, setSubjects] = useState([])
  const [domains, setDomains] = useState([])
  const [subjectId, setSubjectId] = useState('')
  const [topicId, setTopicId] = useState('')
  const [generating, setGenerating] = useState(false)
  const [essayGenerating, setEssayGenerating] = useState(false)
  const [questions, setQuestions] = useState([])
  const [answers, setAnswers] = useState({})
  const [wrongNotes, setWrongNotes] = useState([])
  const [stats, setStats] = useState(null)
  const [reviewQueue, setReviewQueue] = useState([])
  const [essayQuestion, setEssayQuestion] = useState(null)
  const [essayText, setEssayText] = useState('')
  const [essayFeedback, setEssayFeedback] = useState(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [loadingSaved, setLoadingSaved] = useState(false)
  const [llmStatus, setLlmStatus] = useState(null)
  const [models, setModels] = useState([])
  const [modelKey, setModelKey] = useState('')

  useEffect(() => {
    handleUnauthorized = () => { setCurrentUser(null); setAuthMode('login') }
    restoreSession()
  }, [])

  useEffect(() => {
    if (!currentUser) return
    request('/subjects').then(setSubjects).catch(showError)
    loadPersonalData()
    refreshLlmStatus()
    // The picker starts on whichever model the server is configured to use.
    request('/llm/models').then((list) => {
      setModels(list)
      setModelKey((current) => current || (list.find((item) => item.is_default) || list[0])?.key || '')
    }).catch(() => {})
  }, [currentUser])

  async function restoreSession() {
    if (!getToken()) { setSessionChecked(true); return }
    try { setCurrentUser(await request('/auth/me')) } catch { storeToken(null) } finally { setSessionChecked(true) }
  }

  async function authenticate(path, payload) {
    setError('')
    const result = await request(path, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)})
    storeToken(result.access_token)
    setCurrentUser(await request('/auth/me'))
    setView('dashboard')
  }

  function logout() {
    storeToken(null)
    setCurrentUser(null); setAuthMode('login'); setView('dashboard'); setError(''); setNotice(''); setLlmStatus(null)
    setModels([]); setModelKey('')
    setSubjects([]); setDomains([]); setSubjectId(''); setTopicId(''); setQuestions([]); setAnswers({})
    setWrongNotes([]); setStats(null); setReviewQueue([])
    setEssayQuestion(null); setEssayText(''); setEssayFeedback(null)
  }

  async function loadPersonalData() {
    try {
      const [notes, userStats, queue] = await Promise.all([
        request('/users/me/wrong-notes'),
        request('/users/me/stats'),
        request('/users/me/review-queue?limit=3'),
      ])
      setWrongNotes(notes); setStats(userStats); setReviewQueue(queue)
    } catch (err) { showError(err) }
  }

  // The model banner is auxiliary, so a failed status check must not replace the page's own error message.
  function refreshLlmStatus() { request('/llm/status').then(setLlmStatus).catch(() => {}) }
  function showError(err) { setError(err.message || '백엔드에 연결할 수 없습니다.') }
  function navigate(nextView) { setError(''); setNotice(''); setView(nextView); if (nextView === 'wrong' || nextView === 'stats' || nextView === 'dashboard') loadPersonalData() }

  async function selectSubject(event) {
    setDomains([]); setTopicId('')
    const id = event.target.value
    setSubjectId(id)
    if (id) setDomains(await request('/subjects/' + id + '/topics'))
  }

  async function generateQuestions(scope, count) {
    const payload = scope === 'subject' ? {subject_id: Number(subjectId), count} : {topic_id: Number(topicId), count}
    if (modelKey) payload.model_key = modelKey
    setGenerating(true); setError(''); setNotice('')
    try {
      const result = await request('/questions/generate', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)})
      setQuestions(result.questions); setAnswers({}); setView('solve')
      setNotice(generationNotice(result))
    } catch (err) { showError(err) } finally { setGenerating(false); refreshLlmStatus() }
  }

  async function loadSavedQuestions(scope, status) {
    const params = new URLSearchParams({status})
    params.set(scope === 'subject' ? 'subject_id' : 'topic_id', scope === 'subject' ? subjectId : topicId)
    setLoadingSaved(true); setError(''); setNotice('')
    try {
      const result = await request('/questions/pool?' + params)
      setQuestions(result); setAnswers({}); setView('solve')
      if (!result.length) setNotice('조건에 맞는 저장된 문제가 없습니다. 풀이 상태를 바꾸거나 새로 생성해 보세요.')
      else setNotice('조건에 맞는 저장된 문제 ' + result.length + '문항을 모두 불러왔습니다.')
    } catch (err) { showError(err) } finally { setLoadingSaved(false) }
  }

  async function startTopic(reviewTopicId) {
    setTopicId(String(reviewTopicId))
    setError(''); setNotice('')
    try {
      // Reviewing means re-solving what is already saved; generating costs LLM quota, so it is the fallback.
      const saved = await request('/questions/pool?status=all&topic_id=' + reviewTopicId)
      if (saved.length) {
        setQuestions(saved); setAnswers({}); setView('solve')
        setNotice('저장된 문제 ' + saved.length + '문항으로 복습합니다.')
        return
      }
      setGenerating(true); setView('solve')
      const payload = {topic_id: reviewTopicId, count: 1}
      if (modelKey) payload.model_key = modelKey
      const result = await request('/questions/generate', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)})
      setQuestions(result.questions); setAnswers({})
      setNotice('저장된 문제가 없어 새로 1문항을 생성했습니다.')
    } catch (err) { showError(err) } finally { setGenerating(false); refreshLlmStatus() }
  }

  async function answer(id, selectedIndex) {
    if (answers[id]) return
    try {
      const result = await request('/questions/' + id + '/answer', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({selected_index: selectedIndex})})
      setAnswers((current) => ({...current, [id]: {...result, selectedIndex}})); loadPersonalData()
    } catch (err) { showError(err) }
  }

  async function retryWrong(questionId) {
    try {
      const result = await request('/questions/' + questionId + '/regenerate-similar', {method: 'POST'})
      setQuestions(result); setAnswers({}); setView('solve')
    } catch (err) { showError(err) } finally { refreshLlmStatus() }
  }

  function retrySame(note) {
    setError(''); setNotice('')
    setQuestions([{id: note.question_id, question_text: note.question_text, choices: note.choices, topic_id: note.topic_id, topic_name: note.topic_name, last_is_correct: false}])
    setAnswers({}); setView('solve')
  }

  async function generateEssay() {
    if (!topicId) return
    setEssayGenerating(true); setError('')
    try { const result = await request('/essay-questions/generate?topic_id=' + topicId); setEssayQuestion(result); setEssayText(''); setEssayFeedback(null); setView('essay') } catch (err) { showError(err) } finally { setEssayGenerating(false); refreshLlmStatus() }
  }

  async function submitEssay() {
    if (!essayQuestion || !essayText.trim()) return
    try { const result = await request('/essay-questions/' + essayQuestion.id + '/submit', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({answer_text: essayText})}); setEssayFeedback(result) } catch (err) { showError(err) } finally { refreshLlmStatus() }
  }

  if (!sessionChecked) return <div className="app-layout"><main className="content-area"><p className="empty">세션을 확인하는 중...</p></main></div>
  if (!currentUser) return <AuthScreen mode={authMode} setMode={(mode) => { setError(''); setAuthMode(mode) }} onSubmit={authenticate} error={error} onError={showError} />

  return <div className="app-layout">
    <aside className="sidebar">
      <button className="brand brand-button" onClick={() => navigate('dashboard')}><span className="brand-mark">K</span><span>KCA Study</span></button>
      <p className="sidebar-label">학습 공간</p>
      <nav className="sidebar-nav">
        <SideItem icon="⌂" label="대시보드" active={view === 'dashboard'} onClick={() => navigate('dashboard')} />
        <SideItem icon="✓" label="문제 풀기" active={view === 'solve'} onClick={() => navigate('solve')} />
        <SideItem icon="✎" label="실기 모드" active={view === 'essay'} onClick={() => navigate('essay')} />
        <SideItem icon="↺" label="오답 노트" active={view === 'wrong'} badge={wrongNotes.length} onClick={() => navigate('wrong')} />
        <SideItem icon="▥" label="학습 통계" active={view === 'stats'} onClick={() => navigate('stats')} />
        {currentUser.is_admin && <SideItem icon="▣" label="콘텐츠 관리" active={view === 'content'} onClick={() => navigate('content')} />}
      </nav>
      <div className="sidebar-bottom">
        <button className="sidebar-profile" onClick={() => navigate('profile')} aria-current={view === 'profile' ? 'page' : undefined}>
          <span className="avatar">{currentUser.name.slice(0, 1)}</span>
          <div><strong>{currentUser.name}</strong><small>{currentUser.is_admin ? '관리자' : '정보보안기사 준비'}</small></div>
        </button>
        <button className="text-button" onClick={logout}>로그아웃</button>
      </div>
    </aside>
    <main className="content-area">
      <header className="topbar"><div><p className="breadcrumb">KCA Study / {viewTitle(view)}</p><h1>{viewTitle(view)}</h1></div></header>
      <ModelBanner status={llmStatus} />
      <div className="view-panel" key={view}>
      {view === 'dashboard' && <Dashboard stats={stats} wrongNotes={wrongNotes} queue={reviewQueue} onNavigate={navigate} onTopic={startTopic} />}
      {view === 'solve' && <Solve subjects={subjects} domains={domains} subjectId={subjectId} topicId={topicId} setTopicId={setTopicId} selectSubject={selectSubject} generate={generateQuestions} generating={generating} loadSaved={loadSavedQuestions} loadingSaved={loadingSaved} notice={notice} questions={questions} answers={answers} answer={answer} models={models} modelKey={modelKey} setModelKey={setModelKey} />}
      {view === 'essay' && <Essay subjects={subjects} domains={domains} subjectId={subjectId} topicId={topicId} generating={essayGenerating} setTopicId={setTopicId} selectSubject={selectSubject} generate={generateEssay} question={essayQuestion} text={essayText} setText={setEssayText} submit={submitEssay} feedback={essayFeedback} />}
      {view === 'wrong' && <WrongNotes notes={wrongNotes} retry={retryWrong} retrySame={retrySame} />}
      {view === 'stats' && <Stats stats={stats} />}
      {view === 'content' && currentUser.is_admin && <ContentManager subjects={subjects} onError={showError} />}
      {view === 'profile' && <Profile user={currentUser} onUpdate={setCurrentUser} />}
      </div>
      {error && <p className="error">{error}</p>}
    </main>
  </div>
}

function AuthScreen({mode, setMode, onSubmit, error, onError}) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const isRegister = mode === 'register'

  async function submit(event) {
    event.preventDefault()
    setBusy(true)
    try {
      if (isRegister) await onSubmit('/auth/register', {email, password, name})
      else await onSubmit('/auth/login', {email, password})
    } catch (err) { onError(err) } finally { setBusy(false) }
  }

  return <div className="auth-layout">
    <form className="content-card auth-card" onSubmit={submit}>
      <div className="brand"><span className="brand-mark">K</span><span>KCA Study</span></div>
      <h2>{isRegister ? '회원가입' : '로그인'}</h2>
      {isRegister && <label>이름<input value={name} onChange={(e) => setName(e.target.value)} placeholder="이름" required /></label>}
      <label>이메일<input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" required /></label>
      <label>비밀번호<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder={isRegister ? '8자 이상' : '비밀번호'} minLength={isRegister ? 8 : undefined} required /></label>
      <button className="primary-action" disabled={busy}>{busy ? '처리 중...' : isRegister ? '가입하고 시작하기' : '로그인'}</button>
      <button type="button" className="text-button" onClick={() => setMode(isRegister ? 'login' : 'register')}>
        {isRegister ? '이미 계정이 있으신가요? 로그인' : '계정이 없으신가요? 회원가입'}
      </button>
      {error && <p className="error">{error}</p>}
    </form>
  </div>
}

function generationNotice({questions, requested, rejected, unverified}) {
  const parts = []
  if (rejected) parts.push('품질 검증·중복 검사에서 ' + rejected + '문항이 반려되었습니다.')
  if (unverified) parts.push('AI 검증을 거치지 못한 ' + unverified + '문항은 출제에서 제외했습니다. 콘텐츠 관리에서 재검증할 수 있습니다.')
  const missing = requested - questions.length - rejected
  if (missing > 0) parts.push('모델이 ' + missing + '문항을 덜 만들었습니다.')
  return parts.length ? '요청한 ' + requested + '문항 중 ' + questions.length + '문항을 만들었습니다. ' + parts.join(' ') : ''
}
function ModelBanner({status}) {
  if (!status?.fallback_active) return null
  const retryAt = new Date(status.fallback_until).toLocaleTimeString('ko-KR', {hour: '2-digit', minute: '2-digit'})
  return <div className="model-banner" role="status"><span aria-hidden="true">⚠</span><div><strong>AI 모델이 로컬 모델로 자동 전환되었습니다.</strong><br />{status.fallback_reason} 지금은 {status.fallback_model}(으)로 문제를 만들고, {retryAt} 이후 {status.primary_model}을(를) 다시 시도합니다.</div></div>
}
function viewTitle(view) { return ({dashboard: '대시보드', solve: '문제 풀기', essay: '실기 모드', wrong: '오답 노트', stats: '학습 통계', content: '콘텐츠 관리', profile: '내 계정'})[view] }
function SideItem({icon, label, active, badge, onClick}) { return <button className={'side-item ' + (active ? 'active' : '')} aria-current={active ? 'page' : undefined} onClick={onClick}><span>{icon}</span>{label}{badge > 0 && <b>{badge}</b>}</button> }

function Dashboard({stats, wrongNotes, queue, onNavigate, onTopic}) {
  const accuracy = stats?.subject_stats?.length ? Math.round(stats.subject_stats.reduce((sum, item) => sum + item.accuracy, 0) / stats.subject_stats.length) : 0
  return <div className="dashboard-grid"><section className="welcome-panel"><p className="eyebrow">TODAY'S STUDY PLAN</p><h2>오늘도 꾸준히<br /><em>보안 역량을 쌓아보세요.</em></h2><button onClick={() => onNavigate('solve')}>학습 시작하기 →</button></section><div className="metric-grid"><Metric label="전체 정답률" value={accuracy + '%'} detail="과목 평균 · 첫 풀이 기준" /><Metric label="최근 7일 학습량" value={stats?.recent_7_days_count || 0} detail="문제 풀이" /><Metric label="오답 노트" value={wrongNotes.length} detail="다시 확인할 문제" /></div><section className="content-card review-card"><div className="section-heading"><div><p className="card-label">REVIEW QUEUE</p><h2>오늘의 복습</h2></div><button className="text-button" onClick={() => onNavigate('wrong')}>전체 보기</button></div>{queue.length ? queue.map((item) => <button className="queue-item" key={item.schedule_id} onClick={() => onTopic(item.topic_id)}><span className="queue-icon">↺</span><span><strong>{item.topic_name}</strong><small>{item.subject_name} · {item.domain_name}</small></span><span className="queue-arrow">→</span></button>) : <p className="empty">오늘 예정된 복습이 없습니다.</p>}</section><section className="content-card weak-card"><div className="section-heading"><div><p className="card-label">FOCUS AREAS</p><h2>취약 영역 Top 3</h2></div><button className="text-button" onClick={() => onNavigate('stats')}>통계 보기</button></div>{stats?.weak_domains?.length ? stats.weak_domains.map((item) => <ProgressRow item={item} key={item.name} />) : <p className="empty">문제를 풀면 취약 영역이 표시됩니다.</p>}</section></div>
}

function Metric({label, value, detail}) { return <div className="metric-card"><span>{label}</span><strong>{value}</strong><small>{detail}</small></div> }
function ProgressRow({item}) { return <div className="progress-row"><div><span>{item.name}</span><strong>{item.accuracy}%</strong></div><div className="progress-track"><i style={{width: item.accuracy + '%'}} /></div><small>{item.correct}/{item.total} 정답</small></div> }
function TopicSelector({subjects, domains, subjectId, topicId, setTopicId, selectSubject, topicDisabled = false, locked = false}) { return <section className="content-card selector"><label>과목<div className="select-shell"><select value={subjectId} onChange={selectSubject} disabled={locked}><option value="" disabled>과목을 선택하세요</option>{subjects.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select></div></label><label>토픽<div className="select-shell"><select value={topicDisabled ? '' : topicId} onChange={(e) => setTopicId(e.target.value)} disabled={locked || topicDisabled || !domains.length}><option value="">{topicDisabled ? '과목 전체에서 출제' : '토픽을 선택하세요'}</option>{domains.map((d) => <optgroup key={d.id} label={d.name}>{d.topics.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}</optgroup>)}</select></div></label></section> }
function GeneratingPanel({title, detail, placeholders = 1}) {
  const [seconds, setSeconds] = useState(0)
  useEffect(() => { const timer = setInterval(() => setSeconds((value) => value + 1), 1000); return () => clearInterval(timer) }, [])
  return <section className="content-card generating-panel"><div className="generating-head"><span className="spinner" aria-hidden="true" /><div role="status"><strong>{title}</strong><small>{detail}</small></div><span className="generating-time">{seconds}초</span></div><div className="skeleton-list" aria-hidden="true">{Array.from({length: placeholders}, (_, index) => <div className="skeleton-card" key={index}><i className="line wide" /><i className="line" /><i className="line" /><i className="line short" /></div>)}</div></section>
}
const MODE_OPTIONS = [['generate', '새로 생성'], ['saved', '저장된 문제 풀기']]
const SCOPE_OPTIONS = [['subject', '과목 전체'], ['topic', '선택한 토픽']]
const COUNT_OPTIONS = [1, 5, 10].map((value) => [value, value + '문항'])
const STATUS_OPTIONS = [['all', '전체'], ['unanswered', '안 푼 문제'], ['wrong', '틀린 문제']]
const QUESTIONS_PER_PAGE = 20
function Segmented({options, value, onChange, disabled}) { return <div className="segmented">{options.map(([optionValue, label]) => <button type="button" key={optionValue} className={value === optionValue ? 'active' : ''} onClick={() => onChange(optionValue)} disabled={disabled}>{label}</button>)}</div> }
// last_is_correct is only present on saved questions: null = never answered, true/false = latest attempt.
function AttemptPill({lastIsCorrect}) { if (lastIsCorrect === undefined) return null; return <span className={'attempt-pill ' + (lastIsCorrect === null ? 'new' : lastIsCorrect ? 'correct' : 'wrong')}>{lastIsCorrect === null ? '안 푼 문제' : lastIsCorrect ? '지난번 정답' : '지난번 오답'}</span> }
function modelOptionLabel(item) { return item.provider === 'gemini' ? 'Gemini ' + item.model.replace(/^gemini-/, '') : item.model }

function ModelPicker({models, value, onChange, disabled}) {
  const [open, setOpen] = useState(false)
  const container = useRef(null)
  const current = models.find((item) => item.key === value) || models[0]

  useEffect(() => {
    if (!open) return
    function closeOnOutside(event) { if (!container.current?.contains(event.target)) setOpen(false) }
    function closeOnEscape(event) { if (event.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', closeOnOutside)
    document.addEventListener('keydown', closeOnEscape)
    return () => { document.removeEventListener('mousedown', closeOnOutside); document.removeEventListener('keydown', closeOnEscape) }
  }, [open])

  if (!current) return null
  return <div className="model-picker" ref={container}>
    <button type="button" className={'model-trigger' + (open ? ' open' : '')} onClick={() => setOpen((previous) => !previous)} disabled={disabled} aria-haspopup="listbox" aria-expanded={open}>
      <span className={'model-dot ' + current.provider} aria-hidden="true" />
      <span className="model-name">{modelOptionLabel(current)}</span>
      <span className="model-caret" aria-hidden="true">▾</span>
    </button>
    {open && <ul className="model-menu" role="listbox">
      {models.map((item) => <li key={item.key}>
        <button type="button" role="option" aria-selected={item.key === value} className={'model-option' + (item.key === value ? ' active' : '')} onClick={() => { onChange(item.key); setOpen(false) }}>
          <span className={'model-dot ' + item.provider} aria-hidden="true" />
          <span className="model-name">{modelOptionLabel(item)}</span>
          <small>{item.provider === 'gemini' ? '클라우드' : '로컬'}</small>
          <span className="model-check" aria-hidden="true">{item.key === value ? '✓' : ''}</span>
        </button>
      </li>)}
    </ul>}
  </div>
}

function Solve({subjects, domains, subjectId, topicId, setTopicId, selectSubject, generate, generating, loadSaved, loadingSaved, notice, questions, answers, answer, models, modelKey, setModelKey}) {
  const [mode, setMode] = useState('generate')
  const [scope, setScope] = useState('subject')
  const [count, setCount] = useState(1)
  const [status, setStatus] = useState('all')
  const [page, setPage] = useState(1)
  const busy = generating || loadingSaved
  const topicNames = Object.fromEntries(domains.flatMap((d) => d.topics.map((t) => [t.id, t.name])))
  const ready = scope === 'subject' ? Boolean(subjectId) : Boolean(topicId)
  const answered = questions.filter((q) => answers[q.id])
  const correct = answered.filter((q) => answers[q.id].is_correct).length
  // A fresh set of questions always starts on the first page.
  useEffect(() => { setPage(1) }, [questions])
  const pageCount = Math.max(1, Math.ceil(questions.length / QUESTIONS_PER_PAGE))
  const pageStart = (Math.min(page, pageCount) - 1) * QUESTIONS_PER_PAGE
  const pageQuestions = questions.slice(pageStart, pageStart + QUESTIONS_PER_PAGE)
  function goToPage(next) { setPage(next); window.scrollTo({top: 0, behavior: 'smooth'}) }
  const scopeName = scope === 'subject' ? (subjects.find((s) => String(s.id) === String(subjectId))?.name || '과목') + ' 전체' : topicNames[topicId] || '선택한 토픽'
  const generatingDetail = (scope === 'subject' ? '여러 토픽에서 문항을 만들고 정답·범위를 검증합니다.' : '문항을 만들고 정답·범위를 검증합니다.') + (count >= 5 ? ' 문항 수가 많거나 로컬 모델을 쓰면 1분 이상 걸릴 수 있습니다.' : '')
  const action = mode === 'generate'
    ? {run: () => generate(scope, count), label: '문제 생성', busyLabel: '문제 생성 중...'}
    : {run: () => loadSaved(scope, status), label: '문제 불러오기', busyLabel: '불러오는 중...'}
  return <><section className="content-card generate-options"><div className="option-group"><span>출제 범위</span><Segmented options={SCOPE_OPTIONS} value={scope} onChange={setScope} disabled={busy} /></div></section><TopicSelector {...{subjects, domains, subjectId, topicId, setTopicId, selectSubject}} topicDisabled={scope === 'subject'} locked={busy} /><section className="content-card generate-options"><div className="option-group"><span>풀이 방식</span><Segmented options={MODE_OPTIONS} value={mode} onChange={setMode} disabled={busy} /></div>{mode === 'generate' ? <><div className="option-group"><span>문항 수</span><Segmented options={COUNT_OPTIONS} value={count} onChange={setCount} disabled={busy} /></div>{models.length > 1 && <div className="option-group"><span>생성 모델</span><ModelPicker models={models} value={modelKey} onChange={setModelKey} disabled={busy} /></div>}</> : <div className="option-group"><span>풀이 상태</span><Segmented options={STATUS_OPTIONS} value={status} onChange={setStatus} disabled={busy} /></div>}</section><button className="primary-action" onClick={action.run} disabled={!ready || busy}>{busy ? <><span className="spinner inline" aria-hidden="true" />{action.busyLabel}</> : action.label}</button>{generating ? <GeneratingPanel title={scopeName + ' · ' + count + '문항 생성 중'} detail={generatingDetail} placeholders={Math.min(count, 3)} /> : <>{notice && <p className="notice" role="status">{notice}</p>}{questions.length > 0 && <p className="solve-status">{answered.length}/{questions.length}문항 풀이 · 정답 {correct}문항{pageCount > 1 ? ' · ' + page + '/' + pageCount + ' 페이지' : ''}</p>}<section className="questions">{pageQuestions.map((q, index) => <article className="content-card question" key={q.id}><div className="question-meta"><p className="card-label">객관식 {pageStart + index + 1}번{(q.topic_name || topicNames[q.topic_id]) ? ' · ' + (q.topic_name || topicNames[q.topic_id]) : ''}</p><AttemptPill lastIsCorrect={q.last_is_correct} />{q.verification_status === 'unverified' && <span className="attempt-pill unverified" title="AI 검증 호출이 실패해 검증을 거치지 못한 문제입니다. 정답과 해설을 한 번 더 확인하세요.">검증 보류</span>}</div><h2>{q.question_text}</h2><div className="choices">{q.choices.map((choice, index) => <button className={answers[q.id] && index === answers[q.id].correct_index ? 'choice correct' : answers[q.id] && index === answers[q.id].selectedIndex ? 'choice wrong' : 'choice'} key={choice} onClick={() => answer(q.id, index)} disabled={Boolean(answers[q.id])}>{index + 1}. {choice}</button>)}</div>{answers[q.id] && <div className={'feedback ' + (answers[q.id].is_correct ? 'correct-text' : 'wrong-text')}>{answers[q.id].is_correct ? '정답입니다.' : '오답입니다.'}<br />{answers[q.id].explanation}{q.last_is_correct !== undefined && q.last_is_correct !== null && <small className="retry-hint">이미 풀었던 문제라 정답률에는 반영되지 않습니다.</small>}</div>}</article>)}</section>{pageCount > 1 && <nav className="pager" aria-label="문제 페이지"><button className="outline-button" onClick={() => goToPage(page - 1)} disabled={page <= 1}>← 이전</button><span className="pager-status">{page} / {pageCount} 페이지<small>{pageStart + 1}–{pageStart + pageQuestions.length}번 문항</small></span><button className="outline-button" onClick={() => goToPage(page + 1)} disabled={page >= pageCount}>다음 →</button></nav>}</>}</> }
function Essay({subjects, domains, subjectId, topicId, setTopicId, selectSubject, generate, generating, question, text, setText, submit, feedback}) { return <><TopicSelector {...{subjects, domains, subjectId, topicId, setTopicId, selectSubject}} locked={generating} /><button className="primary-action" onClick={generate} disabled={!topicId || generating}>{generating ? <><span className="spinner inline" aria-hidden="true" />실기 문제 생성 중...</> : '실기 문제 생성'}</button>{generating ? <GeneratingPanel title="실기 문제 생성 중" detail="문제와 모범답안, 채점 키워드를 함께 만듭니다." /> : question && <article className="content-card essay-card"><p className="card-label">실기 서술형</p><h2>{question.question_text}</h2><textarea value={text} onChange={(e) => setText(e.target.value)} placeholder="답안을 입력하세요." rows="8" /><button className="primary-action" onClick={submit} disabled={!text.trim()}>답안 제출 및 채점</button>{feedback && <EssayFeedback feedback={feedback} />}</article>}</> }
function EssayFeedback({feedback}) { return <div className="essay-feedback"><h2>점수: {feedback.score}점</h2><p>{feedback.feedback_text}</p><h3>포함된 키워드</h3><div className="keyword-list">{feedback.covered_keywords.map((item) => <span className="keyword covered" key={item.keyword}>{item.keyword} +{item.points}</span>)}</div><h3>누락된 키워드</h3><div className="keyword-list">{feedback.missing_keywords.map((item) => <span className="keyword missing" key={item.keyword}>{item.keyword} -{item.points}</span>)}</div><p><strong>개선 제안:</strong> {feedback.improvement_suggestion}</p><p className="disclaimer">{feedback.disclaimer}</p></div> }
function WrongNotes({notes, retry, retrySame}) { return <section className="content-card"><div className="section-heading"><div><p className="card-label">MISTAKE REVIEW</p><h2>오답 노트</h2></div><span className="count-pill">{notes.length}문제</span></div>{notes.length ? notes.map((note) => <article className="wrong-note" key={note.question_id + '-' + note.answered_at}><div><p className="card-label">{note.topic_name}</p><h3>{note.question_text}</h3><small>{note.summary_text}</small></div><div className="wrong-note-actions"><button onClick={() => retrySame(note)}>다시 풀기 →</button><button className="outline-button" onClick={() => retry(note.question_id)}>비슷한 문제 풀기</button></div></article>) : <p className="empty">아직 저장된 오답이 없습니다. 문제를 풀어보세요.</p>}</section> }
function Stats({stats}) { return <section className="stats-grid"><div className="content-card"><p className="card-label">SUBJECT ACCURACY</p><h2>과목별 정답률</h2><p className="stats-hint">문제별 첫 풀이 결과로 계산합니다. 이미 푼 문제를 다시 푼 결과는 반영하지 않습니다.</p>{stats?.subject_stats?.length ? stats.subject_stats.map((item) => <ProgressRow item={item} key={item.name} />) : <p className="empty">문제 풀이 데이터가 없습니다.</p>}</div><div className="content-card"><p className="card-label">DOMAIN ACCURACY</p><h2>영역별 정답률</h2>{stats?.domain_stats?.length ? stats.domain_stats.map((item) => <ProgressRow item={item} key={item.name} />) : <p className="empty">문제 풀이 데이터가 없습니다.</p>}</div></section> }

function ContentManager({subjects, onError}) {
  const [documents, setDocuments] = useState([])
  const [detail, setDetail] = useState(null)
  const [topicGroups, setTopicGroups] = useState([])
  const [uploading, setUploading] = useState(false)
  const [form, setForm] = useState({title: '', docType: '요약노트'})
  const [file, setFile] = useState(null)
  const [reverifying, setReverifying] = useState(false)
  const [reverifyResult, setReverifyResult] = useState('')
  const refresh = async () => { try { setDocuments(await request('/admin/documents')) } catch (err) { onError(err) } }
  useEffect(() => { refresh() }, [])
  async function showDetail(document) {
    try {
      // Documents cover every subject, so a chunk can be reassigned to any Topic.
      const [nextDetail, ...subjectDomains] = await Promise.all([request('/admin/documents/' + document.id + '/status'), ...subjects.map((subject) => request('/subjects/' + subject.id + '/topics'))])
      setDetail(nextDetail); setTopicGroups(subjects.map((subject, index) => ({name: subject.name, topics: subjectDomains[index].flatMap((domain) => domain.topics)})))
    } catch (err) { onError(err) }
  }
  async function upload(event) {
    event.preventDefault()
    if (!file || !form.title.trim()) return onError(new Error('제목과 파일을 모두 입력하세요.'))
    const data = new FormData()
    data.append('title', form.title); data.append('doc_type', form.docType); data.append('file', file)
    try { setUploading(true); const document = await request('/admin/documents/upload', {method: 'POST', body: data}); setFile(null); setForm({title: '', docType: '요약노트'}); await refresh(); await showDetail(document) } catch (err) { onError(err) } finally { setUploading(false) }
  }
  async function reassign(embeddingId, topicId) {
    try { await request('/admin/documents/' + detail.id + '/embeddings/' + embeddingId, {method: 'PATCH', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({topic_id: Number(topicId)})}); await showDetail(detail) } catch (err) { onError(err) }
  }
  async function reverify() {
    setReverifying(true); setReverifyResult('')
    try {
      const result = await request('/questions/reverify', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({limit: 20})})
      if (!result.checked) setReverifyResult('재검증할 문제가 없습니다.')
      else setReverifyResult(result.checked + '문항을 검증해 ' + result.passed + '문항이 통과했습니다.' + (result.failed ? ' ' + result.failed + '문항은 계속 출제에서 제외됩니다.' : ''))
    } catch (err) { onError(err) } finally { setReverifying(false) }
  }
  async function reprocess(id) { try { await request('/admin/documents/' + id + '/reprocess', {method: 'POST'}); await refresh() } catch (err) { onError(err) } }
  async function remove(id) { if (!window.confirm('문서와 연결된 임베딩을 삭제할까요?')) return; try { await request('/admin/documents/' + id, {method: 'DELETE'}); if (detail?.id === id) setDetail(null); await refresh() } catch (err) { onError(err) } }
  return <div className="content-manager"><section className="content-card"><p className="card-label">ADMIN · INGESTION</p><h2>학습 자료 업로드</h2><form className="upload-form" onSubmit={upload}><label>제목<input value={form.title} onChange={(e) => setForm({...form, title: e.target.value})} placeholder="예: 개인정보보호법 개정 요약" /></label><label>문서 유형<select value={form.docType} onChange={(e) => setForm({...form, docType: e.target.value})}>{['이론서', '법령', '기출문제', '요약노트', '출제경향'].map((type) => <option key={type}>{type}</option>)}</select></label><label>파일 (PDF/TXT, 최대 20MB)<input type="file" accept=".pdf,.txt,text/plain,application/pdf" onChange={(e) => setFile(e.target.files?.[0] || null)} /></label><button disabled={uploading}>{uploading ? '등록 중...' : '업로드 및 처리 시작'}</button></form><p className="upload-help">자료는 전체 5과목 38개 세부항목을 대상으로 조각마다 자동 분류되고, 문제를 만들 때 해당 세부항목의 참고 자료로 쓰입니다. 어떤 세부항목과도 관련 없는 조각(표지, 목차 등)은 제외되며, 문서 속 지시문은 따르지 않습니다.</p></section><section className="content-card"><div className="section-heading"><div><p className="card-label">SOURCE DOCUMENTS</p><h2>업로드 문서</h2></div><button className="text-button" onClick={refresh}>새로고침</button></div>{documents.length ? documents.map((document) => <div className="document-row" key={document.id}><button className="document-main" onClick={() => showDetail(document)}><strong>{document.title}</strong><small>{document.doc_type} · {statusLabel(document.status)} · v{document.version}</small></button><button className="outline-button" onClick={() => reprocess(document.id)}>재처리</button><button className="danger-button" onClick={() => remove(document.id)}>삭제</button></div>) : <p className="empty">등록된 문서가 없습니다.</p>}</section><section className="content-card"><div className="section-heading"><div><p className="card-label">QUESTION VERIFICATION</p><h2>검증 보류 문제</h2></div></div><p className="upload-help">AI 검증 호출이 실패해 검증을 거치지 못한 문제는 출제에서 제외됩니다. 재검증해서 통과하면 다시 출제됩니다. 한 번에 최대 20문항을 API 호출 1회로 검사합니다.</p><button className="primary-action" onClick={reverify} disabled={reverifying}>{reverifying ? <><span className="spinner inline" aria-hidden="true" />재검증 중...</> : '검증 보류 문제 재검증'}</button>{reverifyResult && <p className="notice" role="status">{reverifyResult}</p>}</section>{detail && <section className="content-card"><div className="section-heading"><div><p className="card-label">TOPIC MAPPING</p><h2>{detail.title}</h2></div><span className={'status-pill ' + detail.status}>{statusLabel(detail.status)}</span></div>{detail.error_message && <p className="error">{detail.error_message}</p>}{detail.embeddings.length ? detail.embeddings.map((embedding) => <div className="chunk-row" key={embedding.id}><p>{embedding.chunk_preview}</p><label>자동 분류 Topic<select value={embedding.topic_id} onChange={(e) => reassign(embedding.id, e.target.value)}>{topicGroups.map((group) => <optgroup label={group.name} key={group.name}>{group.topics.map((topic) => <option value={topic.id} key={topic.id}>{topic.name}</option>)}</optgroup>)}</select></label></div>) : <p className="empty">처리 완료 후 청크와 자동 분류 결과가 여기에 표시됩니다.</p>}</section>}</div>
}

function statusLabel(status) { return ({'처리중': '처리중', '완료': '완료', '실패': '실패'})[status] || status }

function Profile({user, onUpdate}) {
  const [name, setName] = useState(user.name)
  const [email, setEmail] = useState(user.email || '')
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  const emailChanged = email !== (user.email || '')
  const wantsPasswordChange = newPassword.length > 0
  const needsCurrentPassword = emailChanged || wantsPasswordChange

  async function submit(event) {
    event.preventDefault()
    setError(''); setMessage('')
    if (wantsPasswordChange && newPassword !== confirmPassword) return setError('새 비밀번호가 서로 일치하지 않습니다.')
    const payload = {}
    if (name !== user.name) payload.name = name
    if (emailChanged) payload.email = email
    if (wantsPasswordChange) payload.new_password = newPassword
    if (needsCurrentPassword) payload.current_password = currentPassword
    if (Object.keys(payload).length === 0) return setMessage('변경된 내용이 없습니다.')
    setBusy(true)
    try {
      const updated = await request('/users/me', {method: 'PATCH', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)})
      onUpdate(updated)
      setCurrentPassword(''); setNewPassword(''); setConfirmPassword('')
      setMessage('저장했습니다.')
    } catch (err) { setError(err.message || '저장하지 못했습니다.') } finally { setBusy(false) }
  }

  return <section className="content-card profile-card">
    <p className="card-label">ACCOUNT</p>
    <h2>내 계정</h2>
    <form className="profile-form" onSubmit={submit}>
      <label>이름<input value={name} onChange={(e) => setName(e.target.value)} minLength={1} maxLength={120} required /></label>
      <label>이메일<input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required /></label>
      {needsCurrentPassword && <label>현재 비밀번호<input type="password" value={currentPassword} onChange={(e) => setCurrentPassword(e.target.value)} placeholder="이메일 또는 비밀번호를 바꾸려면 입력하세요" required /></label>}
      <div className="profile-password-change">
        <p className="card-label">비밀번호 변경</p>
        <label>새 비밀번호<input type="password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} placeholder="8자 이상 · 바꾸지 않으려면 비워두세요" minLength={8} maxLength={200} /></label>
        {wantsPasswordChange && <label>새 비밀번호 확인<input type="password" value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} required /></label>}
      </div>
      <button className="primary-action" disabled={busy}>{busy ? '저장 중...' : '저장'}</button>
      {message && <p className="profile-message" role="status">{message}</p>}
      {error && <p className="error">{error}</p>}
    </form>
  </section>
}

export default App
