import { useEffect, useState } from 'react'

const API = 'http://localhost:8000'
const USER_ID = 1

async function request(path, options) {
  const response = await fetch(API + path, options)
  const data = await response.json()
  if (!response.ok) throw new Error(data.detail || '요청을 처리하지 못했습니다.')
  return data
}

function App() {
  const [view, setView] = useState('dashboard')
  const [subjects, setSubjects] = useState([])
  const [domains, setDomains] = useState([])
  const [topicId, setTopicId] = useState('')
  const [questions, setQuestions] = useState([])
  const [answers, setAnswers] = useState({})
  const [wrongNotes, setWrongNotes] = useState([])
  const [stats, setStats] = useState(null)
  const [reviewQueue, setReviewQueue] = useState([])
  const [essayQuestion, setEssayQuestion] = useState(null)
  const [essayText, setEssayText] = useState('')
  const [essayFeedback, setEssayFeedback] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    request('/subjects').then(setSubjects).catch(showError)
    loadPersonalData()
  }, [])

  async function loadPersonalData() {
    try {
      const [notes, userStats, queue] = await Promise.all([
        request('/users/' + USER_ID + '/wrong-notes'),
        request('/users/' + USER_ID + '/stats'),
        request('/users/' + USER_ID + '/review-queue?limit=3'),
      ])
      setWrongNotes(notes); setStats(userStats); setReviewQueue(queue)
    } catch (err) { showError(err) }
  }

  function showError(err) { setError(err.message || '백엔드에 연결할 수 없습니다.') }
  function navigate(nextView) { setError(''); setView(nextView); if (nextView === 'wrong' || nextView === 'stats' || nextView === 'dashboard') loadPersonalData() }

  async function selectSubject(event) {
    setDomains([]); setTopicId('')
    const id = event.target.value
    if (id) setDomains(await request('/subjects/' + id + '/topics'))
  }

  async function generateQuestions() {
    try {
      const result = await request('/questions/generate', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({topic_id: Number(topicId), count: 1})})
      setQuestions(result); setAnswers({}); setView('solve')
    } catch (err) { showError(err) }
  }

  async function startTopic(reviewTopicId) {
    setTopicId(String(reviewTopicId))
    try {
      const result = await request('/questions/generate', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({topic_id: reviewTopicId, count: 1})})
      setQuestions(result); setAnswers({}); setView('solve')
    } catch (err) { showError(err) }
  }

  async function answer(id, selectedIndex) {
    if (answers[id]) return
    try {
      const result = await request('/questions/' + id + '/answer', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({selected_index: selectedIndex, user_id: USER_ID})})
      setAnswers((current) => ({...current, [id]: {...result, selectedIndex}})); loadPersonalData()
    } catch (err) { showError(err) }
  }

  async function retryWrong(questionId) {
    try {
      const result = await request('/questions/' + questionId + '/regenerate-similar', {method: 'POST'})
      setQuestions(result); setAnswers({}); setView('solve')
    } catch (err) { showError(err) }
  }

  async function generateEssay() {
    if (!topicId) return
    try { const result = await request('/essay-questions/generate?topic_id=' + topicId); setEssayQuestion(result); setEssayText(''); setEssayFeedback(null); setView('essay') } catch (err) { showError(err) }
  }

  async function submitEssay() {
    if (!essayQuestion || !essayText.trim()) return
    try { const result = await request('/essay-questions/' + essayQuestion.id + '/submit', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({user_id: USER_ID, answer_text: essayText})}); setEssayFeedback(result) } catch (err) { showError(err) }
  }

  return <div className="app-layout">
    <aside className="sidebar">
      <div className="brand"><span className="brand-mark">K</span><span>KCA Study</span></div>
      <p className="sidebar-label">학습 공간</p>
      <nav className="sidebar-nav">
        <SideItem icon="⌂" label="대시보드" active={view === 'dashboard'} onClick={() => navigate('dashboard')} />
        <SideItem icon="✓" label="문제 풀기" active={view === 'solve'} onClick={() => navigate('solve')} />
        <SideItem icon="✎" label="실기 모드" active={view === 'essay'} onClick={() => navigate('essay')} />
        <SideItem icon="↺" label="오답 노트" active={view === 'wrong'} badge={wrongNotes.length} onClick={() => navigate('wrong')} />
        <SideItem icon="▥" label="학습 통계" active={view === 'stats'} onClick={() => navigate('stats')} />
        <SideItem icon="▣" label="콘텐츠 관리" active={view === 'content'} onClick={() => navigate('content')} />
      </nav>
      <div className="sidebar-bottom"><span className="avatar">U</span><div><strong>학습자</strong><small>정보보안기사 준비</small></div></div>
    </aside>
    <main className="content-area">
      <header className="topbar"><div><p className="breadcrumb">KCA Study / {viewTitle(view)}</p><h1>{viewTitle(view)}</h1></div><div className="header-status">● 오늘도 학습 중</div></header>
      {view === 'dashboard' && <Dashboard stats={stats} wrongNotes={wrongNotes} queue={reviewQueue} onNavigate={navigate} onTopic={startTopic} />}
      {view === 'solve' && <Solve subjects={subjects} domains={domains} topicId={topicId} setTopicId={setTopicId} selectSubject={selectSubject} generate={generateQuestions} questions={questions} answers={answers} answer={answer} />}
      {view === 'essay' && <Essay subjects={subjects} domains={domains} topicId={topicId} setTopicId={setTopicId} selectSubject={selectSubject} generate={generateEssay} question={essayQuestion} text={essayText} setText={setEssayText} submit={submitEssay} feedback={essayFeedback} />}
      {view === 'wrong' && <WrongNotes notes={wrongNotes} retry={retryWrong} />}
      {view === 'stats' && <Stats stats={stats} />}
      {view === 'content' && <ContentManager subjects={subjects} onError={showError} />}
      {error && <p className="error">{error}</p>}
    </main>
  </div>
}

function viewTitle(view) { return ({dashboard: '대시보드', solve: '문제 풀기', essay: '실기 모드', wrong: '오답 노트', stats: '학습 통계', content: '콘텐츠 관리'})[view] }
function SideItem({icon, label, active, badge, onClick}) { return <button className={'side-item ' + (active ? 'active' : '')} onClick={onClick}><span>{icon}</span>{label}{badge > 0 && <b>{badge}</b>}</button> }

function Dashboard({stats, wrongNotes, queue, onNavigate, onTopic}) {
  const accuracy = stats?.subject_stats?.length ? Math.round(stats.subject_stats.reduce((sum, item) => sum + item.accuracy, 0) / stats.subject_stats.length) : 0
  return <div className="dashboard-grid"><section className="welcome-panel"><p className="eyebrow">TODAY'S STUDY PLAN</p><h2>오늘도 꾸준히<br /><em>보안 역량을 쌓아보세요.</em></h2><button onClick={() => onNavigate('solve')}>학습 시작하기 →</button></section><div className="metric-grid"><Metric label="전체 정답률" value={accuracy + '%'} detail="과목 평균" /><Metric label="최근 7일 학습량" value={stats?.recent_7_days_count || 0} detail="문제 풀이" /><Metric label="오답 노트" value={wrongNotes.length} detail="다시 확인할 문제" /></div><section className="content-card review-card"><div className="section-heading"><div><p className="card-label">REVIEW QUEUE</p><h2>오늘의 복습</h2></div><button className="text-button" onClick={() => onNavigate('wrong')}>전체 보기</button></div>{queue.length ? queue.map((item) => <button className="queue-item" key={item.schedule_id} onClick={() => onTopic(item.topic_id)}><span className="queue-icon">↺</span><span><strong>{item.topic_name}</strong><small>{item.subject_name} · {item.domain_name}</small></span><span className="queue-arrow">→</span></button>) : <p className="empty">오늘 예정된 복습이 없습니다.</p>}</section><section className="content-card weak-card"><div className="section-heading"><div><p className="card-label">FOCUS AREAS</p><h2>취약 영역 Top 3</h2></div><button className="text-button" onClick={() => onNavigate('stats')}>통계 보기</button></div>{stats?.weak_domains?.length ? stats.weak_domains.map((item) => <ProgressRow item={item} key={item.name} />) : <p className="empty">문제를 풀면 취약 영역이 표시됩니다.</p>}</section></div>
}

function Metric({label, value, detail}) { return <div className="metric-card"><span>{label}</span><strong>{value}</strong><small>{detail}</small></div> }
function ProgressRow({item}) { return <div className="progress-row"><div><span>{item.name}</span><strong>{item.accuracy}%</strong></div><div className="progress-track"><i style={{width: item.accuracy + '%'}} /></div><small>{item.correct}/{item.total} 정답</small></div> }
function TopicSelector({subjects, domains, topicId, setTopicId, selectSubject}) { return <section className="content-card selector"><label>과목<select onChange={selectSubject} defaultValue=""><option value="" disabled>과목을 선택하세요</option>{subjects.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select></label><label>토픽<select value={topicId} onChange={(e) => setTopicId(e.target.value)} disabled={!domains.length}><option value="">토픽을 선택하세요</option>{domains.map((d) => <optgroup key={d.id} label={d.name}>{d.topics.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}</optgroup>)}</select></label></section> }
function Solve({subjects, domains, topicId, setTopicId, selectSubject, generate, questions, answers, answer}) { return <><TopicSelector {...{subjects, domains, topicId, setTopicId, selectSubject}} /><button className="primary-action" onClick={generate} disabled={!topicId}>문제 생성</button><section className="questions">{questions.map((q) => <article className="content-card question" key={q.id}><p className="card-label">객관식 문제 #{q.id}</p><h2>{q.question_text}</h2><div className="choices">{q.choices.map((choice, index) => <button className={answers[q.id] && index === answers[q.id].correct_index ? 'choice correct' : answers[q.id] && index === answers[q.id].selectedIndex ? 'choice wrong' : 'choice'} key={choice} onClick={() => answer(q.id, index)} disabled={Boolean(answers[q.id])}>{index + 1}. {choice}</button>)}</div>{answers[q.id] && <div className={'feedback ' + (answers[q.id].is_correct ? 'correct-text' : 'wrong-text')}>{answers[q.id].is_correct ? '정답입니다.' : '오답입니다.'}<br />{answers[q.id].explanation}</div>}</article>)}</section></> }
function Essay({subjects, domains, topicId, setTopicId, selectSubject, generate, question, text, setText, submit, feedback}) { return <><TopicSelector {...{subjects, domains, topicId, setTopicId, selectSubject}} /><button className="primary-action" onClick={generate} disabled={!topicId}>실기 문제 생성</button>{question && <article className="content-card essay-card"><p className="card-label">실기 서술형</p><h2>{question.question_text}</h2><textarea value={text} onChange={(e) => setText(e.target.value)} placeholder="답안을 입력하세요." rows="8" /><button className="primary-action" onClick={submit} disabled={!text.trim()}>답안 제출 및 채점</button>{feedback && <EssayFeedback feedback={feedback} />}</article>}</> }
function EssayFeedback({feedback}) { return <div className="essay-feedback"><h2>점수: {feedback.score}점</h2><p>{feedback.feedback_text}</p><h3>포함된 키워드</h3><div className="keyword-list">{feedback.covered_keywords.map((item) => <span className="keyword covered" key={item.keyword}>{item.keyword} +{item.points}</span>)}</div><h3>누락된 키워드</h3><div className="keyword-list">{feedback.missing_keywords.map((item) => <span className="keyword missing" key={item.keyword}>{item.keyword} -{item.points}</span>)}</div><p><strong>개선 제안:</strong> {feedback.improvement_suggestion}</p><p className="disclaimer">{feedback.disclaimer}</p></div> }
function WrongNotes({notes, retry}) { return <section className="content-card"><div className="section-heading"><div><p className="card-label">MISTAKE REVIEW</p><h2>오답 노트</h2></div><span className="count-pill">{notes.length}문제</span></div>{notes.length ? notes.map((note) => <article className="wrong-note" key={note.question_id + '-' + note.answered_at}><div><p className="card-label">{note.topic_name}</p><h3>{note.question_text}</h3><small>{note.summary_text}</small></div><button onClick={() => retry(note.question_id)}>비슷한 문제 풀기 →</button></article>) : <p className="empty">아직 저장된 오답이 없습니다. 문제를 풀어보세요.</p>}</section> }
function Stats({stats}) { return <section className="stats-grid"><div className="content-card"><p className="card-label">SUBJECT ACCURACY</p><h2>과목별 정답률</h2>{stats?.subject_stats?.length ? stats.subject_stats.map((item) => <ProgressRow item={item} key={item.name} />) : <p className="empty">문제 풀이 데이터가 없습니다.</p>}</div><div className="content-card"><p className="card-label">DOMAIN ACCURACY</p><h2>영역별 정답률</h2>{stats?.domain_stats?.length ? stats.domain_stats.map((item) => <ProgressRow item={item} key={item.name} />) : <p className="empty">문제 풀이 데이터가 없습니다.</p>}</div></section> }

function ContentManager({subjects, onError}) {
  const [documents, setDocuments] = useState([])
  const [detail, setDetail] = useState(null)
  const [topics, setTopics] = useState([])
  const [uploading, setUploading] = useState(false)
  const [form, setForm] = useState({title: '', docType: '요약노트', subjectId: ''})
  const [file, setFile] = useState(null)
  const refresh = async () => { try { setDocuments(await request('/admin/documents')) } catch (err) { onError(err) } }
  useEffect(() => { refresh() }, [])
  async function showDetail(document) {
    try {
      const [nextDetail, domains] = await Promise.all([request('/admin/documents/' + document.id + '/status'), request('/subjects/' + document.subject_id + '/topics')])
      setDetail(nextDetail); setTopics(domains.flatMap((domain) => domain.topics))
    } catch (err) { onError(err) }
  }
  async function upload(event) {
    event.preventDefault()
    if (!file || !form.subjectId || !form.title.trim()) return onError(new Error('제목, 과목, 파일을 모두 입력하세요.'))
    const data = new FormData()
    data.append('title', form.title); data.append('doc_type', form.docType); data.append('subject_id', form.subjectId); data.append('file', file)
    try { setUploading(true); const document = await request('/admin/documents/upload', {method: 'POST', body: data}); setFile(null); setForm({title: '', docType: '요약노트', subjectId: ''}); await refresh(); await showDetail(document) } catch (err) { onError(err) } finally { setUploading(false) }
  }
  async function reassign(embeddingId, topicId) {
    try { await request('/admin/documents/' + detail.id + '/embeddings/' + embeddingId, {method: 'PATCH', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({topic_id: Number(topicId)})}); await showDetail(detail) } catch (err) { onError(err) }
  }
  async function reprocess(id) { try { await request('/admin/documents/' + id + '/reprocess', {method: 'POST'}); await refresh() } catch (err) { onError(err) } }
  async function remove(id) { if (!window.confirm('문서와 연결된 임베딩을 삭제할까요?')) return; try { await request('/admin/documents/' + id, {method: 'DELETE'}); if (detail?.id === id) setDetail(null); await refresh() } catch (err) { onError(err) } }
  return <div className="content-manager"><section className="content-card"><p className="card-label">ADMIN · INGESTION</p><h2>학습 자료 업로드</h2><form className="upload-form" onSubmit={upload}><label>제목<input value={form.title} onChange={(e) => setForm({...form, title: e.target.value})} placeholder="예: 개인정보보호법 개정 요약" /></label><label>문서 유형<select value={form.docType} onChange={(e) => setForm({...form, docType: e.target.value})}>{['이론서', '법령', '기출문제', '요약노트'].map((type) => <option key={type}>{type}</option>)}</select></label><label>대상 과목<select value={form.subjectId} onChange={(e) => setForm({...form, subjectId: e.target.value})}><option value="">과목 선택</option>{subjects.map((subject) => <option value={subject.id} key={subject.id}>{subject.name}</option>)}</select></label><label>파일 (PDF/TXT, 최대 20MB)<input type="file" accept=".pdf,.txt,text/plain,application/pdf" onChange={(e) => setFile(e.target.files?.[0] || null)} /></label><button disabled={uploading}>{uploading ? '등록 중...' : '업로드 및 처리 시작'}</button></form><p className="upload-help">문서 내용의 지시문은 무시하고 Topic 분류와 임베딩 생성에만 사용합니다.</p></section><section className="content-card"><div className="section-heading"><div><p className="card-label">SOURCE DOCUMENTS</p><h2>업로드 문서</h2></div><button className="text-button" onClick={refresh}>새로고침</button></div>{documents.length ? documents.map((document) => <div className="document-row" key={document.id}><button className="document-main" onClick={() => showDetail(document)}><strong>{document.title}</strong><small>{document.doc_type} · {statusLabel(document.status)} · v{document.version}</small></button><button className="outline-button" onClick={() => reprocess(document.id)}>재처리</button><button className="danger-button" onClick={() => remove(document.id)}>삭제</button></div>) : <p className="empty">등록된 문서가 없습니다.</p>}</section>{detail && <section className="content-card"><div className="section-heading"><div><p className="card-label">TOPIC MAPPING</p><h2>{detail.title}</h2></div><span className={'status-pill ' + detail.status}>{statusLabel(detail.status)}</span></div>{detail.error_message && <p className="error">{detail.error_message}</p>}{detail.embeddings.length ? detail.embeddings.map((embedding) => <div className="chunk-row" key={embedding.id}><p>{embedding.chunk_preview}</p><label>자동 분류 Topic<select value={embedding.topic_id} onChange={(e) => reassign(embedding.id, e.target.value)}>{topics.map((topic) => <option value={topic.id} key={topic.id}>{topic.name}</option>)}</select></label></div>) : <p className="empty">처리 완료 후 청크와 자동 분류 결과가 여기에 표시됩니다.</p>}</section>}</div>
}

function statusLabel(status) { return ({'처리중': '처리중', '완료': '완료', '실패': '실패'})[status] || status }

export default App
