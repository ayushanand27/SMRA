import type { ComponentPropsWithoutRef, ReactNode } from 'react'
import { Children, isValidElement, useCallback, useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import {
  createVideoJob,
  explainFromImages,
  explainFromPdf,
  explainFromText,
  fetchSlideDeckBlob,
  fetchVideoBlob,
  fileToDataUrl,
  generateIllustration,
  generateQuiz,
  generateSlideDeck,
  generateSpeech,
  generateFlashcards,
  generateInfographic,
  fetchSpeechBlob,
  getVideoJob,
  OUTPUT_LANGUAGE_LABELS,
  type ExplainResponse,
  type FlashcardsResponse,
  type ModelStack,
  type OutputLanguageCode,
  type QuizResponse,
  type SlideDeckResponse,
  type SpeechResponse,
  type OpensourceAnimationPreset,
  type VideoJob,
  type VideoJobStack,
  type LessonOverviewStyle,
} from './api'
import { MermaidDiagram } from './MermaidDiagram'
import './App.css'

type Mode = 'text' | 'images' | 'pdf'
type MainTab = 'learn' | 'video' | 'quiz' | 'slides' | 'flashcards' | 'infographic' | 'listen' | 'images'

/** Fenced ```mermaid in explanation_markdown — render with the same pipeline as `mermaid_diagram`. */
function MarkdownPre({ children, ...rest }: ComponentPropsWithoutRef<'pre'>) {
  const arr = Children.toArray(children)
  const codeEl = arr.find((c) => isValidElement(c) && c.type === 'code')
  if (isValidElement(codeEl)) {
    const cls = String((codeEl.props as { className?: string }).className || '')
    if (cls.includes('language-mermaid')) {
      const raw = String((codeEl.props as { children?: ReactNode }).children ?? '').replace(/\n$/, '')
      return (
        <div className="diagram-box diagram-in-md">
          <MermaidDiagram code={raw} />
        </div>
      )
    }
  }
  return <pre {...rest}>{children}</pre>
}

function briefKindLabel(b: { kind: string; suggested_format: string }): string {
  const f = (b.suggested_format || '').toLowerCase()
  const k = (b.kind || '').toLowerCase()
  if (f.includes('animation') || f.includes('storyboard') || k.includes('animation')) return 'Animation idea'
  if (f.includes('mermaid') || k.includes('diagram') || k.includes('timeline')) return 'Diagram / sequence'
  return 'Visual idea'
}

function App() {
  const [mainTab, setMainTab] = useState<MainTab>('learn')
  const [mode, setMode] = useState<Mode>('text')
  const [outputLanguage, setOutputLanguage] = useState<OutputLanguageCode>('english')
  const [stack, setStack] = useState<ModelStack>('opensource')
  const [topicHint, setTopicHint] = useState('')
  const [chapterText, setChapterText] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const [pdfFile, setPdfFile] = useState<File | null>(null)
  const [pdfOcrPages, setPdfOcrPages] = useState(true)
  const [pdfOcrImages, setPdfOcrImages] = useState(true)

  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<ExplainResponse | null>(null)

  const [quizDifficulty, setQuizDifficulty] = useState<'remedial' | 'standard' | 'advanced'>('standard')
  const [quizCount, setQuizCount] = useState(5)
  const [quizLoading, setQuizLoading] = useState(false)
  const [quizError, setQuizError] = useState<string | null>(null)
  const [quizData, setQuizData] = useState<QuizResponse | null>(null)
  const [answers, setAnswers] = useState<Record<string, number>>({})
  const [currentQuestionIdx, setCurrentQuestionIdx] = useState(0)

  const [slideCount, setSlideCount] = useState(8)
  const [slidesLoading, setSlidesLoading] = useState(false)
  const [slidesError, setSlidesError] = useState<string | null>(null)
  const [slideDeck, setSlideDeck] = useState<SlideDeckResponse | null>(null)
  const [slideIndex, setSlideIndex] = useState(0)

  const [listenBusy, setListenBusy] = useState(false)
  const [listenErr, setListenErr] = useState<string | null>(null)
  const [speechInfo, setSpeechInfo] = useState<SpeechResponse | null>(null)
  const [audioUrl, setAudioUrl] = useState<string | null>(null)
  const [openaiTtsVoice, setOpenaiTtsVoice] = useState<
    'alloy' | 'echo' | 'fable' | 'onyx' | 'nova' | 'shimmer'
  >('nova')
  const [openaiTtsModel, setOpenaiTtsModel] = useState<'tts-1' | 'tts-1-hd'>('tts-1')
  const [edgeVoiceOverride, setEdgeVoiceOverride] = useState('')

  const [flashCount, setFlashCount] = useState(12)
  const [flashLoading, setFlashLoading] = useState(false)
  const [flashError, setFlashError] = useState<string | null>(null)
  const [flashData, setFlashData] = useState<FlashcardsResponse | null>(null)
  const [flashCardIndex, setFlashCardIndex] = useState(0)
  const [flashFlipped, setFlashFlipped] = useState(false)

  const [infoBusy, setInfoBusy] = useState(false)
  const [infoErr, setInfoErr] = useState<string | null>(null)
  const [infoImage, setInfoImage] = useState<{ src: string; prompt: string } | null>(null)

  const [videoPrompt, setVideoPrompt] = useState('')
  const [useRefImage] = useState(true)
  const [clipLength, setClipLength] = useState<'4' | '8' | '12' | 'approx30'>('4')
  const [vModel, setVModel] = useState('sora-2')
  const [opensourceAnimation, setOpensourceAnimation] = useState<OpensourceAnimationPreset>('motion_plus')
  /** Video tab only — does not change the Learn/quiz model stack. */
  const [videoSource, setVideoSource] = useState<VideoJobStack>('opensource')
  const [lessonOverviewText, setLessonOverviewText] = useState('')
  const [lessonOverviewStyle, setLessonOverviewStyle] = useState<LessonOverviewStyle>('explainer')
  const [lessonPexelsBg, setLessonPexelsBg] = useState(false)
  const [vSize] = useState<string>('')
  const [, setVideoJob] = useState<VideoJob | null>(null)
  const [videoBusy, setVideoBusy] = useState(false)
  const [videoErr, setVideoErr] = useState<string | null>(null)
  const [videoUrl, setVideoUrl] = useState<string | null>(null)

  const [illustrationSrc, setIllustrationSrc] = useState<string | null>(null)
  const [illustrationBusy, setIllustrationBusy] = useState(false)
  const [illustrationErr, setIllustrationErr] = useState<string | null>(null)
  const [illustrationUsePexels, setIllustrationUsePexels] = useState(false)

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const stopPoll = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
  }, [])

  useEffect(() => {
    return () => {
      stopPoll()
      if (videoUrl) URL.revokeObjectURL(videoUrl)
      if (audioUrl) URL.revokeObjectURL(audioUrl)
    }
  }, [stopPoll, videoUrl, audioUrl])

  useEffect(() => {
    if (videoSource === 'opensource') {
      setVModel(opensourceAnimation === 'motion_plus' ? 'opensource-local-motion-plus' : 'opensource-local-animation')
    } else if (videoSource === 'pexels') {
      setVModel('pexels-stock-video')
    } else if (videoSource === 'lesson_overview') {
      setVModel('lesson-overview-explainer')
    } else if (videoSource === 'openai') {
      setVModel((prev) => (prev === 'sora-2' || prev === 'sora-2-pro' ? prev : 'sora-2'))
    }
  }, [videoSource, opensourceAnimation])

  /** Quiz / slides / etc.: send both source chapter (if any) and the generated lesson so the LLM is grounded in what you provided. */
  const getLessonContextFromExplain = (explain: ExplainResponse | null): string | null => {
    const chunks: string[] = []
    if ((mode === 'text' || mode === 'pdf') && chapterText.trim()) {
      chunks.push(chapterText.trim())
    }
    if (explain) {
      const parts = [
        explain.explanation_markdown?.trim(),
        ...(explain.simple_examples || []).map((s) => String(s).trim()).filter(Boolean),
        ...(explain.visual_briefs || []).map((b) => `${b.title}. ${b.description}`.trim()),
      ].filter(Boolean) as string[]
      if (parts.length > 0) {
        chunks.push(parts.join('\n\n'))
      }
    }
    const merged = chunks.join('\n\n---\n\n').trim()
    return merged.length > 0 ? merged : null
  }

  const derivedQuizTopic =
    topicHint.trim() ||
    (mode === 'text' && chapterText.trim() ? chapterText.trim().split('\n')[0].slice(0, 120) : '') ||
    (mode === 'pdf' && pdfFile ? pdfFile.name.replace(/\.pdf$/i, '').slice(0, 120) : '') ||
    'Current chapter topic'

  const derivedQuizContext = getLessonContextFromExplain(result)

  const runQuizPipeline = async (ctx: string | null, topic: string) => {
    setQuizError(null)
    setQuizData(null)
    setAnswers({})
    setQuizLoading(true)
    try {
      const res = await generateQuiz({
        topic,
        context_text: ctx,
        output_language: outputLanguage,
        stack,
        question_count: quizCount,
        difficulty: quizDifficulty,
      })
      setQuizData(res)
      setCurrentQuestionIdx(0)
    } catch (e) {
      setQuizError(e instanceof Error ? e.message : String(e))
    } finally {
      setQuizLoading(false)
    }
  }

  const runSlideDeckPipeline = async (ctx: string | null, topic: string) => {
    setSlidesError(null)
    setSlideDeck(null)
    setSlideIndex(0)
    setSlidesLoading(true)
    try {
      const res = await generateSlideDeck({
        topic,
        context_text: ctx,
        output_language: outputLanguage,
        stack,
        slide_count: slideCount,
      })
      setSlideDeck(res)
    } catch (e) {
      setSlidesError(e instanceof Error ? e.message : String(e))
    } finally {
      setSlidesLoading(false)
    }
  }

  const runFlashcardsPipeline = async (ctx: string | null, topic: string) => {
    setFlashError(null)
    setFlashData(null)
    setFlashCardIndex(0)
    setFlashFlipped(false)
    if (!ctx?.trim()) {
      setFlashError('No lesson text was available to build flashcards from.')
      return
    }
    setFlashLoading(true)
    try {
      const res = await generateFlashcards({
        topic,
        context_text: ctx,
        output_language: outputLanguage,
        stack,
        card_count: flashCount,
      })
      setFlashData(res)
    } catch (e) {
      setFlashError(e instanceof Error ? e.message : String(e))
    } finally {
      setFlashLoading(false)
    }
  }

  const runInfographicPipeline = async (ctx: string | null, topic: string) => {
    setInfoErr(null)
    setInfoImage(null)
    if (!ctx?.trim()) {
      setInfoErr('No lesson text was available for the infographic.')
      return
    }
    setInfoBusy(true)
    try {
      const res = await generateInfographic({
        topic,
        context_text: ctx,
        output_language: outputLanguage,
        stack,
      })
      setInfoImage({
        src: `data:${res.mime_type};base64,${res.image_base64}`,
        prompt: res.image_prompt_used || '',
      })
    } catch (e) {
      setInfoErr(e instanceof Error ? e.message : String(e))
    } finally {
      setInfoBusy(false)
    }
  }

  const runLessonAudioPipeline = async (ctx: string | null) => {
    setListenErr(null)
    setSpeechInfo(null)
    if (audioUrl) {
      URL.revokeObjectURL(audioUrl)
      setAudioUrl(null)
    }
    if (!ctx?.trim()) {
      setListenErr('No lesson text was available for audio.')
      return
    }
    setListenBusy(true)
    try {
      const res = await generateSpeech({
        context_text: ctx,
        output_language: outputLanguage,
        stack,
        openai_voice: openaiTtsVoice,
        openai_tts_model: openaiTtsModel,
        edge_voice: edgeVoiceOverride.trim() || null,
      })
      setSpeechInfo(res)
      const blob = await fetchSpeechBlob(res.audio_id)
      const url = URL.createObjectURL(blob)
      setAudioUrl(url)
    } catch (e) {
      setListenErr(e instanceof Error ? e.message : String(e))
    } finally {
      setListenBusy(false)
    }
  }

  const runExplain = async () => {
    setError(null)
    setResult(null)
    setQuizError(null)
    setQuizData(null)
    setAnswers({})
    setSlidesError(null)
    setSlideDeck(null)
    setSlideIndex(0)
    setFlashError(null)
    setFlashData(null)
    setFlashCardIndex(0)
    setFlashFlipped(false)
    setInfoImage(null)
    setInfoErr(null)
    setSpeechInfo(null)
    setListenErr(null)
    if (audioUrl) {
      URL.revokeObjectURL(audioUrl)
      setAudioUrl(null)
    }
    setIllustrationSrc(null)
    setIllustrationErr(null)

    if (mode === 'text') {
      if (!chapterText.trim()) {
        setError('Paste some chapter text first.')
        return
      }
    } else if (mode === 'pdf') {
      if (!pdfFile) {
        setError('Choose a PDF file first.')
        return
      }
    } else if (files.length === 0) {
      setError('Choose one or more screenshots.')
      return
    }

    const topic =
      topicHint.trim() ||
      (mode === 'text' && chapterText.trim() ? chapterText.trim().split('\n')[0].slice(0, 120) : '') ||
      (mode === 'pdf' && pdfFile ? pdfFile.name.replace(/\.pdf$/i, '').slice(0, 120) : '') ||
      'Current chapter topic'

    setLoading(true)
    try {
      let data: ExplainResponse
      if (mode === 'text') {
        data = await explainFromText(chapterText, outputLanguage, topicHint, stack)
      } else if (mode === 'pdf') {
        if (!pdfFile) throw new Error('No PDF file.')
        data = await explainFromPdf(pdfFile, outputLanguage, topicHint, stack, pdfOcrPages, pdfOcrImages)
        const extracted = data.source_text_used_for_context?.trim()
        if (extracted) setChapterText(extracted)
      } else {
        data = await explainFromImages(files, outputLanguage, topicHint, stack)
      }
      setResult(data)

      const ctx = getLessonContextFromExplain(data)

      await runQuizPipeline(ctx, topic)
      await runSlideDeckPipeline(ctx, topic)
      await runFlashcardsPipeline(ctx, topic)
      await runInfographicPipeline(ctx, topic)
      await runLessonAudioPipeline(ctx)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }



  const quizAnsweredCount = quizData
    ? quizData.questions.filter((q) => answers[q.id] !== undefined).length
    : 0
  const quizCorrectCount = quizData
    ? quizData.questions.filter((q) => {
        const picked = answers[q.id]
        return picked !== undefined && picked === q.correct_option_index
      }).length
    : 0

  const runSlideDeck = async () => {
    await runSlideDeckPipeline(derivedQuizContext, derivedQuizTopic)
  }

  const runLessonAudio = async () => {
    const ctx = derivedQuizContext
    if (!ctx?.trim()) {
      setListenErr('Add chapter text on Learn, or run Generate explanation first (required for Screenshots mode).')
      return
    }
    await runLessonAudioPipeline(ctx)
  }

  const runFlashcards = async () => {
    const ctx = derivedQuizContext
    if (!ctx?.trim()) {
      setFlashError('Add chapter text on Learn, or run Generate explanation first (needed for Screenshots mode).')
      return
    }
    await runFlashcardsPipeline(ctx, derivedQuizTopic)
  }

  const runInfographic = async () => {
    const ctx = derivedQuizContext
    if (!ctx?.trim()) {
      setInfoErr('Add chapter text on Learn, or run Generate explanation first (needed for Screenshots mode).')
      return
    }
    await runInfographicPipeline(ctx, derivedQuizTopic)
  }

  const downloadLessonAudio = () => {
    if (!audioUrl || !speechInfo) return
    const a = document.createElement('a')
    a.href = audioUrl
    a.download = speechInfo.filename
    a.rel = 'noopener'
    a.click()
  }

  const downloadSlideDeck = async () => {
    if (!slideDeck) return
    try {
      const blob = await fetchSlideDeckBlob(slideDeck.deck_id)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = slideDeck.filename
      a.rel = 'noopener'
      a.click()
      URL.revokeObjectURL(url)
    } catch (e) {
      setSlidesError(e instanceof Error ? e.message : String(e))
    }
  }

  useEffect(() => {
    if (mainTab !== 'slides' || !slideDeck?.slides.length) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'ArrowLeft') {
        e.preventDefault()
        setSlideIndex((i) => Math.max(0, i - 1))
      }
      if (e.key === 'ArrowRight') {
        e.preventDefault()
        setSlideIndex((i) => Math.min(slideDeck.slides.length - 1, i + 1))
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [mainTab, slideDeck])

  useEffect(() => {
    if (mainTab !== 'flashcards' || !flashData?.cards.length) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'ArrowLeft') {
        e.preventDefault()
        setFlashCardIndex((i) => Math.max(0, i - 1))
        setFlashFlipped(false)
      }
      if (e.key === 'ArrowRight') {
        e.preventDefault()
        setFlashCardIndex((i) => Math.min(flashData.cards.length - 1, i + 1))
        setFlashFlipped(false)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [mainTab, flashData])

  const runQuiz = async () => {
    await runQuizPipeline(derivedQuizContext, derivedQuizTopic)
  }

  const startVideo = async () => {
    setVideoErr(null)
    if (videoSource === 'lesson_overview') {
      if (lessonOverviewText.trim().length < 120) {
        setVideoErr(
          'Lesson overview needs at least 120 characters of source text. Paste a chapter or click Fill from lesson.',
        )
        return
      }
    } else if (!videoPrompt.trim()) {
      setVideoErr('Add an animation prompt (short sentences separated by periods work best).')
      return
    }
    setVideoBusy(true)
    if (videoUrl) {
      URL.revokeObjectURL(videoUrl)
      setVideoUrl(null)
    }
    try {
      let refUrl: string | null = null
      if (videoSource === 'openai' && useRefImage && mode === 'images' && files.length > 0) {
        refUrl = await fileToDataUrl(files[0])
      }
      const job = await createVideoJob({
        prompt:
          videoSource === 'lesson_overview'
            ? lessonOverviewText.trim().slice(0, 400) || 'Lesson overview'
            : videoPrompt.trim(),
        seconds: clipLength === 'approx30' ? '12' : clipLength,
        model: vModel,
        size: vSize.trim() || null,
        input_reference_image_url: videoSource === 'openai' ? refUrl : null,
        chain_target_seconds:
          videoSource === 'pexels' || videoSource === 'lesson_overview'
            ? null
            : clipLength === 'approx30'
              ? 30
              : null,
        stack: videoSource,
        opensource_animation: videoSource === 'opensource' ? opensourceAnimation : null,
        ...(videoSource === 'lesson_overview'
          ? {
              lesson_source_text: lessonOverviewText.trim(),
              lesson_overview_style: lessonOverviewStyle,
              output_language: outputLanguage,
              lesson_use_pexels_background: lessonPexelsBg,
              lesson_llm_stack: stack,
            }
          : {}),
      })
      setVideoJob(job)
      stopPoll()

      const tick = async () => {
        try {
          const j = await getVideoJob(job.id)
          setVideoJob(j)
          if (j.status === 'completed') {
            stopPoll()
            const blob = await fetchVideoBlob(job.id)
            const url = URL.createObjectURL(blob)
            setVideoUrl(url)
            setVideoBusy(false)
          } else if (j.status === 'failed') {
            stopPoll()
            setVideoBusy(false)
            setVideoErr(j.error?.message || 'Video generation failed.')
          }
        } catch (e) {
          stopPoll()
          setVideoBusy(false)
          setVideoErr(e instanceof Error ? e.message : String(e))
        }
      }

      await tick()
      pollRef.current = setInterval(tick, job.id.startsWith('lovid_') ? 6000 : 4000)
    } catch (e) {
      setVideoBusy(false)
      setVideoErr(e instanceof Error ? e.message : String(e))
    }
  }

  const runIllustration = async () => {
    if (!result?.visual_briefs?.length) return
    const first = result.visual_briefs[0]
    const prompt = `${first.title}. ${first.description}`.slice(0, 3500)
    setIllustrationErr(null)
    setIllustrationBusy(true)
    try {
      const src = await generateIllustration(prompt, stack, illustrationUsePexels ? 'pexels' : 'ai')
      setIllustrationSrc(src)
    } catch (e) {
      setIllustrationErr(e instanceof Error ? e.message : String(e))
    } finally {
      setIllustrationBusy(false)
    }
  }

  return (
    <div className="app">
      <header className="app-header">
        <div className="app-brand-logo-wrap">
          <img className="app-brand-logo" src="/smartskale.png" alt="SmartSkale" />
        </div>
        <div className="app-header-main app-header-panel">
          <h1>ClassroomAI</h1>
          <p className="sub">
            Create a lesson from chapter text, screenshots, or a PDF — then review it with a quiz, flashcards, slides,
            an infographic, and audio.
          </p>
        </div>
      </header>

      <div className="tabs">
        <button type="button" className={mainTab === 'learn' ? 'active' : ''} onClick={() => setMainTab('learn')}>
          Learn
        </button>
        <button type="button" className={mainTab === 'images' ? 'active' : ''} onClick={() => setMainTab('images')}>
          Images
        </button>
        <button type="button" className={mainTab === 'video' ? 'active' : ''} onClick={() => setMainTab('video')}>
          Video
        </button>
        <button type="button" className={mainTab === 'quiz' ? 'active' : ''} onClick={() => setMainTab('quiz')}>
          Quiz
        </button>
        <button type="button" className={mainTab === 'slides' ? 'active' : ''} onClick={() => setMainTab('slides')}>
          Slides
        </button>
        <button
          type="button"
          className={mainTab === 'flashcards' ? 'active' : ''}
          onClick={() => setMainTab('flashcards')}
        >
          Flashcards
        </button>
        <button type="button" className={mainTab === 'infographic' ? 'active' : ''} onClick={() => setMainTab('infographic')}>
          Infographic
        </button>
        <button type="button" className={mainTab === 'listen' ? 'active' : ''} onClick={() => setMainTab('listen')}>
          Listen
        </button>
      </div>

      <div className="grid">
        <label className="field">
          Model stack
          <select value={stack} onChange={(e) => setStack(e.target.value as ModelStack)}>
            <option value="opensource">Open Source (Ollama + Local tools)</option>
            <option value="openai">OpenAI (API key/subscription)</option>
          </select>
        </label>
        <label className="field">
          Output language
          <select value={outputLanguage} onChange={(e) => setOutputLanguage(e.target.value as OutputLanguageCode)}>
            <option value="english">English</option>
            <option value="hindi">Hindi (देवनागरी)</option>
            <option value="roman_hindi">Roman Hindi (Latin letters)</option>
          </select>
        </label>
      </div>
      <p className="hint app-lang-hint">
        All explanations, examples, and downstream content (quiz, slides, audio, etc.) are produced in{' '}
        <strong>{OUTPUT_LANGUAGE_LABELS[outputLanguage]}</strong>. Choose the language before you generate.
      </p>

      {mainTab === 'learn' && (
        <>
          <div className="tabs" style={{ marginTop: '0.75rem' }}>
            <button type="button" className={mode === 'text' ? 'active' : ''} onClick={() => setMode('text')}>
              Text
            </button>
            <button type="button" className={mode === 'images' ? 'active' : ''} onClick={() => setMode('images')}>
              Screenshots
            </button>
            <button type="button" className={mode === 'pdf' ? 'active' : ''} onClick={() => setMode('pdf')}>
              PDF
            </button>
          </div>

          <div className="grid">
            <label className="field">
              Topic focus (optional)
              <input value={topicHint} onChange={(e) => setTopicHint(e.target.value)} placeholder="e.g. concave mirrors only" />
            </label>
            {mode === 'text' ? (
              <label className="field">
                Chapter text
                <textarea
                  value={chapterText}
                  onChange={(e) => setChapterText(e.target.value)}
                  placeholder={`Paste chapter text here. The explanation will be structured with headings, concrete examples, and ${OUTPUT_LANGUAGE_LABELS[outputLanguage]} throughout.`}
                />
              </label>
            ) : mode === 'pdf' ? (
              <>
                <label className="field">
                  PDF document
                  <input
                    type="file"
                    accept="application/pdf,.pdf"
                    onChange={(e) => setPdfFile(e.target.files?.[0] ?? null)}
                  />
                </label>
                <div className="row" style={{ flexWrap: 'wrap', gap: '1rem', alignItems: 'center' }}>
                  <label className="row" style={{ gap: '0.4rem', cursor: 'pointer' }}>
                    <input type="checkbox" checked={pdfOcrPages} onChange={(e) => setPdfOcrPages(e.target.checked)} />
                    <span className="hint">OCR scanned / sparse pages (needs Tesseract on server)</span>
                  </label>
                  <label className="row" style={{ gap: '0.4rem', cursor: 'pointer' }}>
                    <input type="checkbox" checked={pdfOcrImages} onChange={(e) => setPdfOcrImages(e.target.checked)} />
                    <span className="hint">OCR text inside embedded images</span>
                  </label>
                </div>
                <p className="hint">
                  The server extracts text page-by-page, tables, and optional OCR, then runs the same explanation pipeline.
                  After generation, extracted text is copied into memory for quiz/slides context. Max 100 pages / 40 MB.
                </p>
              </>
            ) : (
              <label className="field">
                Screenshots (multiple)
                <input type="file" accept="image/*" multiple onChange={(e) => setFiles(e.target.files ? Array.from(e.target.files) : [])} />
              </label>
            )}
            <div className="row learn-actions">
              <button type="button" className="primary" disabled={loading} onClick={runExplain}>{loading ? 'Creating lesson…' : 'Start Learn'}</button>
            </div>
            {error && <p className="err">{error}</p>}
          </div>

          {result && (
            <section className="panel">
              <h2>Explanation</h2>
              {result.output_language_used && (
                <p className="hint explanation-lang-badge">
                  Written in: {OUTPUT_LANGUAGE_LABELS[result.output_language_used]}
                </p>
              )}
              {result.pdf_extraction_notes?.trim() ? (
                <p className="hint" style={{ marginTop: '0.35rem' }}>
                  PDF extraction: {result.pdf_extraction_notes}
                </p>
              ) : null}
              <div className="md">
                <ReactMarkdown components={{ pre: MarkdownPre }}>{result.explanation_markdown}</ReactMarkdown>
              </div>

              {result.mermaid_diagram && (
                <>
                  <h2 style={{ marginTop: '1.25rem' }}>Diagram</h2>
                  <div className="diagram-box"><MermaidDiagram code={result.mermaid_diagram} /></div>
                  {result.diagram_caption?.trim() ? (
                    <p className="hint diagram-legend">{result.diagram_caption.trim()}</p>
                  ) : null}
                </>
              )}

              {result.simple_examples.length > 0 && (
                <>
                  <h2 style={{ marginTop: '1.25rem' }}>Concrete examples</h2>
                  <ul className="examples">{result.simple_examples.map((ex, i) => <li key={i}>{ex}</li>)}</ul>
                </>
              )}

              {result.visual_briefs.length > 0 && (
                <>
                  <h2 style={{ marginTop: '1.25rem' }}>Visual ideas</h2>
                  <div className="briefs">
                    {result.visual_briefs.map((b, i) => (
                      <div className="brief" key={i}><span className="brief-badge">{briefKindLabel(b)}</span><strong>{b.title}</strong><div>{b.description}</div></div>
                    ))}
                  </div>
                  <div className="row" style={{ marginTop: '0.75rem', flexWrap: 'wrap', gap: '0.75rem', alignItems: 'center' }}>
                    <label className="row" style={{ gap: '0.4rem', cursor: 'pointer' }}>
                      <input
                        type="checkbox"
                        checked={illustrationUsePexels}
                        onChange={(e) => setIllustrationUsePexels(e.target.checked)}
                      />
                      <span className="hint">Use stock image</span>
                    </label>
                    <button type="button" className="secondary" disabled={illustrationBusy || loading} onClick={runIllustration}>
                      {illustrationBusy ? (illustrationUsePexels ? 'Loading…' : 'Drawing…') : illustrationUsePexels ? 'Generate stock image' : 'Generate image'}
                    </button>
                  </div>
                  {illustrationUsePexels && (
                    <p className="hint" style={{ marginTop: '0.35rem' }}>
                      Uses the first visual idea as search keywords. Needs <code>PEXELS_API_KEY</code> on the server.
                    </p>
                  )}
                  {illustrationErr && <p className="err">{illustrationErr}</p>}
                  {illustrationSrc && (
                    <img
                      className="illustration-img"
                      src={illustrationSrc}
                      alt={illustrationUsePexels ? 'Pexels stock photo' : 'Generated illustration'}
                    />
                  )}
                  {/* --- Show all images at the bottom --- */}
                  <div style={{ marginTop: '2rem' }}>
                    <h2>Visual gallery</h2>
                    <div className="asset-grid">
                      {result.visual_briefs.map((b, i) => (
                        <article className="asset-card" key={`asset-${i}`}>
                          <div className="brief-badge">{briefKindLabel(b)}</div>
                          <strong>{b.title}</strong>
                          <div className="hint asset-desc">{b.description}</div>
                          {b.src ? (
                            <img className="illustration-img asset-img" src={b.src} alt={b.title || 'Visual'} />
                          ) : null}
                          {b.mermaid_diagram ? (
                            <div className="diagram-box asset-diagram">
                              <MermaidDiagram code={b.mermaid_diagram} />
                            </div>
                          ) : null}
                        </article>
                      ))}
                      {illustrationSrc ? (
                        <article className="asset-card">
                          <strong>{illustrationUsePexels ? 'Stock image' : 'Image'}</strong>
                          <div className="hint asset-desc">
                            {illustrationUsePexels
                              ? 'A searchable stock image related to the current lesson.'
                              : 'An illustration related to the lesson topic.'}
                          </div>
                          <img
                            className="illustration-img asset-img"
                            src={illustrationSrc}
                            alt={illustrationUsePexels ? 'Pexels stock photo' : 'Illustration'}
                          />
                        </article>
                      ) : null}
                      {infoImage ? (
                        <article className="asset-card">
                          <div className="brief-badge">Reference image</div>
                          <strong>Lesson image</strong>
                          <div className="hint asset-desc">{infoImage.prompt || 'A lesson-related supporting image.'}</div>
                          <img className="illustration-img asset-img" src={infoImage.src} alt={infoImage.prompt || 'Relevant image'} />
                        </article>
                      ) : null}
                      {result.visual_briefs.filter((b) => b.src || b.mermaid_diagram).length === 0 && !illustrationSrc && !infoImage && (
                        <span style={{ color: '#888', fontStyle: 'italic' }}>
                          No visuals yet.
                        </span>
                      )}
                    </div>
                  </div>
                </>
              )}
            </section>
          )}
        </>
      )}

      {mainTab === 'video' && (
        <section className="panel video-area">
          <h2>Short video clip</h2>
          <p className="hint">
            Generate explanation on Learn does not create video — use Generate clip here. Choose a clip source below.
            <strong> Lesson overview</strong> builds a narrated multi-slide MP4 from your text (similar in spirit to
            Notebook LM video overviews: script + voice + visuals — not Google&apos;s proprietary pipeline). For{' '}
            <strong>Pexels</strong>, use short search-style keywords. For local or Sora, short factual sentences work well.
            {videoSource === 'openai' && mode === 'images' && files.length > 0 && (
              <>
                {' '}
                With Screenshots mode and files on Learn, Sora can use your first screenshot as a reference.
              </>
            )}
          </p>
          <label className="field" style={{ marginTop: '0.75rem' }}>
            Clip source
            <select
              value={videoSource}
              onChange={(e) => setVideoSource(e.target.value as VideoJobStack)}
            >
              <option value="opensource">Local animation (no API credits)</option>
              <option value="openai">OpenAI Sora (generative)</option>
              <option value="pexels">Pexels stock video (needs PEXELS_API_KEY)</option>
              <option value="lesson_overview">Lesson overview (narrated explainer from your text)</option>
            </select>
          </label>
          {videoSource === 'lesson_overview' ? (
            <>
              <div className="row" style={{ marginTop: '0.75rem', flexWrap: 'wrap', gap: '0.75rem', alignItems: 'flex-end' }}>
                <label className="field" style={{ minWidth: '200px' }}>
                  Overview style
                  <select
                    value={lessonOverviewStyle}
                    onChange={(e) => setLessonOverviewStyle(e.target.value as LessonOverviewStyle)}
                  >
                    <option value="explainer">Explainer (~6 segments)</option>
                    <option value="brief">Brief (~4 segments)</option>
                  </select>
                </label>
                <label className="row" style={{ gap: '0.4rem', cursor: 'pointer', alignItems: 'center' }}>
                  <input
                    type="checkbox"
                    checked={lessonPexelsBg}
                    onChange={(e) => setLessonPexelsBg(e.target.checked)}
                  />
                  <span className="hint">Stock image backgrounds (Pexels)</span>
                </label>
                <button
                  type="button"
                  className="secondary"
                  disabled={!derivedQuizContext}
                  onClick={() => derivedQuizContext && setLessonOverviewText(derivedQuizContext)}
                >
                  Fill from lesson
                </button>
              </div>
              <label className="field" style={{ marginTop: '0.75rem' }}>
                Source text (chapter, notes, or pasted explanation — min. 120 characters)
                <textarea
                  value={lessonOverviewText}
                  onChange={(e) => setLessonOverviewText(e.target.value)}
                  rows={14}
                  placeholder="Paste the material you want turned into a narrated overview video. After running Generate explanation on Learn, use Fill from lesson to pull chapter + explanation."
                />
              </label>
            </>
          ) : (
            <label className="field" style={{ marginTop: '0.75rem' }}>
              {videoSource === 'pexels' ? 'Search keywords' : 'Animation prompt'}
              <textarea
                value={videoPrompt}
                onChange={(e) => setVideoPrompt(e.target.value)}
                rows={6}
                placeholder={
                  videoSource === 'pexels'
                    ? 'e.g. plant cell, science lab, teacher explaining'
                    : 'e.g. Chloroplasts trap sunlight. Water splits. CO2 becomes sugar. Oxygen is released.'
                }
              />
            </label>
          )}
          <div className="row" style={{ marginTop: '0.75rem' }}>
            {videoSource !== 'pexels' && videoSource !== 'lesson_overview' && (
              <label className="field" style={{ minWidth: '200px' }}>
                Length
                <select value={clipLength} onChange={(e) => setClipLength(e.target.value as '4' | '8' | '12' | 'approx30')}>
                  <option value="4">4s</option>
                  <option value="8">8s</option>
                  <option value="12">12s</option>
                  <option value="approx30">~30s</option>
                </select>
              </label>
            )}
            <label className="field" style={{ minWidth: '220px' }}>
              {videoSource === 'openai' ? 'Model' : videoSource === 'opensource' ? 'Local animation' : ' '}
              {videoSource === 'lesson_overview' ? (
                <span className="hint" style={{ display: 'block', paddingTop: '0.35rem' }}>
                  Uses Model stack + output language from the header
                </span>
              ) : videoSource === 'openai' ? (
                <select value={vModel} onChange={(e) => setVModel(e.target.value)}>
                  <option value="sora-2">sora-2</option>
                  <option value="sora-2-pro">sora-2-pro</option>
                </select>
              ) : videoSource === 'opensource' ? (
                <select
                  value={opensourceAnimation}
                  onChange={(e) => setOpensourceAnimation(e.target.value as OpensourceAnimationPreset)}
                >
                  <option value="classic">Classic (lightweight)</option>
                  <option value="motion_plus">Motion+ (smoother, richer 2D)</option>
                </select>
              ) : (
                <span className="hint" style={{ display: 'block', paddingTop: '0.35rem' }}>
                  Original clip length from Pexels
                </span>
              )}
            </label>
            <button type="button" className="primary" style={{ alignSelf: 'flex-end' }} disabled={videoBusy || loading} onClick={startVideo}>
              {videoBusy
                ? videoSource === 'lesson_overview'
                  ? 'Building overview…'
                  : 'Rendering…'
                : videoSource === 'lesson_overview'
                  ? 'Build overview video'
                  : 'Generate clip'}
            </button>
          </div>
          {videoSource === 'opensource' && (
            <p className="hint" style={{ marginTop: '0.5rem' }}>
              Local clips are 2D lesson-style animations. Motion+ adds smoother motion and framing; for photoreal
              generative video, choose OpenAI (Sora), or try Pexels for real stock footage.
            </p>
          )}
          {videoSource === 'pexels' && (
            <p className="hint" style={{ marginTop: '0.5rem' }}>
              Returns one landscape stock clip from the Pexels catalog (not AI-generated). Follow Pexels license terms for
              your use case. Requires <code>PEXELS_API_KEY</code> in server <code>.env</code>.
            </p>
          )}
          {videoSource === 'lesson_overview' && (
            <p className="hint" style={{ marginTop: '0.5rem' }}>
              The server builds a script (via your LLM stack), narrates each segment with TTS, renders title slides, and
              stitches an MP4. Generation can take several minutes. Optional Pexels backgrounds need{' '}
              <code>PEXELS_API_KEY</code>. This is an open-source-style explainer, not Google Notebook LM&apos;s cinematic
              pipeline.
            </p>
          )}
          {videoErr && <p className="err">{videoErr}</p>}
          {videoUrl && <video src={videoUrl} controls playsInline />}
        </section>
      )}

      {mainTab === 'quiz' && (
        <section className="panel">
          <h2>Generate Quiz</h2>
          <div className="grid">
            <p className="hint">
              After you run Generate explanation on Learn, a quiz is created automatically. You can also regenerate here
              with different difficulty or question count. Questions are grounded in your lesson: in text mode we send both
              your pasted chapter (or PDF extraction) and the generated explanation; in screenshots mode we use the
              explanation (and related fields) from Learn.
              <br />
              Topic label: <strong>{derivedQuizTopic}</strong>
            </p>
            <div className="row">
              <label className="field" style={{ minWidth: '180px' }}>
                Difficulty
                <select value={quizDifficulty} onChange={(e) => setQuizDifficulty(e.target.value as 'remedial' | 'standard' | 'advanced')}>
                  <option value="remedial">Remedial</option>
                  <option value="standard">Standard</option>
                  <option value="advanced">Advanced</option>
                </select>
              </label>
              <label className="field" style={{ minWidth: '130px' }}>
                Questions
                <input type="number" min={1} max={15} value={quizCount} onChange={(e) => setQuizCount(Math.max(1, Math.min(15, Number(e.target.value) || 5)))} />
              </label>
              <button type="button" className="primary" style={{ alignSelf: 'flex-end' }} disabled={quizLoading || loading} onClick={runQuiz}>
                {quizLoading ? 'Generating…' : 'Generate quiz'}
              </button>
            </div>
          </div>
          {quizError && <p className="err">{quizError}</p>}

          {quizData && quizData.questions.length > 0 && (
            <div style={{ marginTop: '1rem' }}>
              {(() => {
                const q = quizData.questions[currentQuestionIdx]
                const selected = answers[q.id]
                const isAnswered = selected !== undefined
                const isCorrect = isAnswered && selected === q.correct_option_index
                const selectedExplanation = isAnswered && q.option_explanations && q.option_explanations[selected] ? q.option_explanations[selected] : null
                return (
                  <div className="brief" key={q.id} style={{ marginBottom: '0.85rem' }}>
                    <div className="row" style={{ justifyContent: 'space-between' }}>
                      <strong>Question {currentQuestionIdx + 1} / {quizData.questions.length}</strong>
                      <span className="hint">Answered: {Object.keys(answers).length}/{quizData.questions.length}</span>
                    </div>
                    <strong style={{ display: 'block', marginTop: '0.5rem' }}>{q.question}</strong>
                    <div className="quiz-options">
                      {q.options.map((opt, oi) => (
                        <label key={oi} className="quiz-option">
                          <input
                            type="radio"
                            name={`q-${q.id}`}
                            checked={selected === oi}
                            onChange={() => setAnswers((prev) => ({ ...prev, [q.id]: oi }))}
                          />
                          <span>{opt}</span>
                        </label>
                      ))}
                    </div>
                    {isAnswered && (
                      <div className={isCorrect ? 'quiz-feedback ok' : 'quiz-feedback bad'}>
                        <strong>{isCorrect ? 'Correct' : 'Not correct'}</strong>
                        <div>{selectedExplanation || (isCorrect ? q.correct_explanation : q.wrong_explanation)}</div>
                        {!isCorrect && (
                          <div style={{ marginTop: '0.25rem' }}>
                            Correct answer: <strong>{q.options[q.correct_option_index]}</strong>
                          </div>
                        )}
                      </div>
                    )}
                    <div className="row" style={{ marginTop: '0.75rem' }}>
                      <button
                        type="button"
                        className="secondary"
                        disabled={currentQuestionIdx === 0}
                        onClick={() => setCurrentQuestionIdx((i) => Math.max(0, i - 1))}
                      >
                        Previous
                      </button>
                      <button
                        type="button"
                        className="secondary"
                        disabled={currentQuestionIdx >= quizData.questions.length - 1}
                        onClick={() => setCurrentQuestionIdx((i) => Math.min(quizData.questions.length - 1, i + 1))}
                      >
                        Next
                      </button>
                    </div>
                  </div>
                )
              })()}
              {quizAnsweredCount === quizData.questions.length && (
                <div className="quiz-feedback ok" style={{ marginTop: '0.75rem' }}>
                  <strong>Final Score: {quizCorrectCount} / {quizData.questions.length}</strong>
                  <div>
                    {quizCorrectCount === quizData.questions.length
                      ? 'Excellent! You answered all questions correctly.'
                      : `You got ${quizCorrectCount} correct. Review explanations and try again.`}
                  </div>
                </div>
              )}
            </div>
          )}
        </section>
      )}

      {mainTab === 'slides' && (
        <section className="panel">
          <h2>Slide deck</h2>
          <p className="hint">
            A deck is created automatically when you run Generate explanation on Learn. Regenerate here to change slide
            count. Decks use a dark cinematic layout (hero title slide + full-bleed backgrounds). Without Pexels, each
            slide gets a generated gradient; with <code>PEXELS_API_KEY</code> in <code>.env</code>, slides use darkened
            stock photos behind text. Preview below, then download to open in PowerPoint or Google Slides.
            <br />
            Topic: <strong>{derivedQuizTopic}</strong>
          </p>
          <div className="row" style={{ flexWrap: 'wrap', gap: '0.75rem', alignItems: 'flex-end' }}>
            <label className="field" style={{ minWidth: '120px' }}>
              Slides (content)
              <input
                type="number"
                min={4}
                max={20}
                value={slideCount}
                onChange={(e) => setSlideCount(Math.max(4, Math.min(20, Number(e.target.value) || 8)))}
              />
            </label>
            <button type="button" className="primary" disabled={slidesLoading || loading} onClick={runSlideDeck}>
              {slidesLoading ? 'Building deck…' : 'Generate slide deck'}
            </button>
            <button type="button" className="secondary" disabled={!slideDeck || slidesLoading} onClick={downloadSlideDeck}>
              Download .pptx
            </button>
          </div>
          {slidesError && <p className="err">{slidesError}</p>}

          {slideDeck && slideDeck.slides.length > 0 && (
            <div className="slide-deck-wrap">
              <div className="slide-deck-header">
                <strong>{slideDeck.deck_title}</strong>
                <span className="hint">
                  Slide {slideIndex + 1} / {slideDeck.slides.length}
                </span>
              </div>
              <div className="slide-frame" aria-live="polite">
                <div className="slide-screen">
                  <h3 className="slide-title">{slideDeck.slides[slideIndex].title}</h3>
                  <ul className="slide-bullets">
                    {slideDeck.slides[slideIndex].bullets.map((b, i) => (
                      <li key={i}>{b}</li>
                    ))}
                  </ul>
                  {slideDeck.slides[slideIndex].photo_attribution ? (
                    <p className="slide-photo-credit">{slideDeck.slides[slideIndex].photo_attribution}</p>
                  ) : null}
                </div>
                {slideDeck.slides[slideIndex].speaker_notes ? (
                  <p className="slide-notes">
                    <span className="slide-notes-label">Speaker notes</span>
                    {slideDeck.slides[slideIndex].speaker_notes}
                  </p>
                ) : null}
              </div>
              <div className="slide-nav">
                <button
                  type="button"
                  className="secondary"
                  disabled={slideIndex === 0}
                  onClick={() => setSlideIndex((i) => Math.max(0, i - 1))}
                >
                  Previous
                </button>
                <div className="slide-dots" role="tablist" aria-label="Slides">
                  {slideDeck.slides.map((_, i) => (
                    <button
                      key={i}
                      type="button"
                      role="tab"
                      aria-selected={i === slideIndex}
                      className={`slide-dot ${i === slideIndex ? 'active' : ''}`}
                      onClick={() => setSlideIndex(i)}
                      aria-label={`Go to slide ${i + 1}`}
                    />
                  ))}
                </div>
                <button
                  type="button"
                  className="secondary"
                  disabled={slideIndex >= slideDeck.slides.length - 1}
                  onClick={() => setSlideIndex((i) => Math.min(slideDeck.slides.length - 1, i + 1))}
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </section>
      )}

      {mainTab === 'infographic' && (
        <section className="panel">
          <h2>Infographic</h2>
          <p className="hint">
            An infographic is also generated when you run Generate explanation on Learn. Generate again here to retry
            or after changing stack. The app asks the model for a layout prompt, then renders with DALL·E 3 (OpenAI) or
            local Stable Diffusion (Open Source). Images avoid readable text by design.
            <br />
            Topic: <strong>{derivedQuizTopic}</strong>
          </p>
          <div className="row">
            <button type="button" className="primary" disabled={infoBusy || loading} onClick={runInfographic}>
              {infoBusy ? 'Generating…' : 'Generate infographic'}
            </button>
          </div>
          {infoErr && <p className="err">{infoErr}</p>}
          {infoImage && (
            <div className="infographic-wrap">
              <img className="infographic-img" src={infoImage.src} alt="Lesson infographic" />
              {infoImage.prompt ? (
                <details className="infographic-prompt-details">
                  <summary>Image prompt used</summary>
                  <pre>{infoImage.prompt}</pre>
                </details>
              ) : null}
            </div>
          )}
        </section>
      )}

      {mainTab === 'flashcards' && (
        <section className="panel">
          <h2>Flashcards</h2>
          <p className="hint">
            Flashcards are created with Generate explanation on Learn. Regenerate here to change card count. Click the
            card or use Flip card; arrow keys move between cards.
            <br />
            Topic: <strong>{derivedQuizTopic}</strong>
          </p>
          <div className="row" style={{ flexWrap: 'wrap', gap: '0.75rem', alignItems: 'flex-end' }}>
            <label className="field" style={{ minWidth: '120px' }}>
              Cards
              <input
                type="number"
                min={4}
                max={40}
                value={flashCount}
                onChange={(e) => setFlashCount(Math.max(4, Math.min(40, Number(e.target.value) || 12)))}
              />
            </label>
            <button type="button" className="primary" disabled={flashLoading || loading} onClick={runFlashcards}>
              {flashLoading ? 'Generating…' : 'Generate flashcards'}
            </button>
          </div>
          {flashError && <p className="err">{flashError}</p>}
          {flashData && flashData.cards.length > 0 && (
            <div className="flashcards-wrap">
              <div className="flashcards-toolbar">
                <span className="hint">
                  Card {flashCardIndex + 1} / {flashData.cards.length}
                </span>
                <button type="button" className="secondary" onClick={() => setFlashFlipped((f) => !f)}>
                  Flip card
                </button>
              </div>
              <div
                className="flashcard-scene"
                role="button"
                tabIndex={0}
                onClick={() => setFlashFlipped((f) => !f)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault()
                    setFlashFlipped((f) => !f)
                  }
                }}
                aria-label="Flashcard; click to flip"
              >
                <div className={`flashcard-inner ${flashFlipped ? 'is-flipped' : ''}`}>
                  <div className="flashcard-face flashcard-front">
                    <span className="flashcard-label">Front</span>
                    <p>{flashData.cards[flashCardIndex].front}</p>
                  </div>
                  <div className="flashcard-face flashcard-back">
                    <span className="flashcard-label">Back</span>
                    <p>{flashData.cards[flashCardIndex].back}</p>
                  </div>
                </div>
              </div>
              <div className="flashcards-nav">
                <button
                  type="button"
                  className="secondary"
                  disabled={flashCardIndex === 0}
                  onClick={(e) => {
                    e.stopPropagation()
                    setFlashCardIndex((i) => Math.max(0, i - 1))
                    setFlashFlipped(false)
                  }}
                >
                  Previous
                </button>
                <button
                  type="button"
                  className="secondary"
                  disabled={flashCardIndex >= flashData.cards.length - 1}
                  onClick={(e) => {
                    e.stopPropagation()
                    setFlashCardIndex((i) => Math.min(flashData.cards.length - 1, i + 1))
                    setFlashFlipped(false)
                  }}
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </section>
      )}

      {mainTab === 'listen' && (
        <section className="panel">
          <h2>Lesson audio</h2>
          <p className="hint">
            Lesson audio is synthesized automatically after Generate explanation on Learn. Use Generate lesson audio here
            to redo with different voice settings. For Hindi or Roman Hindi, text is translated in plain text by your
            chat model; keep Ollama running for Open Source. Then edge-tts or OpenAI Speech API synthesizes audio.
            <br />
            Topic: <strong>{derivedQuizTopic}</strong>
          </p>
          <div className="grid" style={{ marginTop: '0.75rem' }}>
            {stack === 'openai' ? (
              <>
                <label className="field">
                  OpenAI voice
                  <select
                    value={openaiTtsVoice}
                    onChange={(e) =>
                      setOpenaiTtsVoice(e.target.value as 'alloy' | 'echo' | 'fable' | 'onyx' | 'nova' | 'shimmer')
                    }
                  >
                    <option value="alloy">alloy</option>
                    <option value="echo">echo</option>
                    <option value="fable">fable</option>
                    <option value="onyx">onyx</option>
                    <option value="nova">nova</option>
                    <option value="shimmer">shimmer</option>
                  </select>
                </label>
                <label className="field">
                  OpenAI TTS model
                  <select value={openaiTtsModel} onChange={(e) => setOpenaiTtsModel(e.target.value as 'tts-1' | 'tts-1-hd')}>
                    <option value="tts-1">tts-1 (faster)</option>
                    <option value="tts-1-hd">tts-1-hd (higher quality)</option>
                  </select>
                </label>
              </>
            ) : (
              <label className="field">
                Edge voice override (optional)
                <input
                  value={edgeVoiceOverride}
                  onChange={(e) => setEdgeVoiceOverride(e.target.value)}
                  placeholder="e.g. hi-IN-SwaraNeural — leave empty for auto by language"
                />
              </label>
            )}
          </div>
          <div className="row" style={{ flexWrap: 'wrap', gap: '0.75rem', marginTop: '0.75rem' }}>
            <button type="button" className="primary" disabled={listenBusy || loading} onClick={runLessonAudio}>
              {listenBusy ? 'Synthesizing…' : 'Generate lesson audio'}
            </button>
            <button type="button" className="secondary" disabled={!audioUrl || !speechInfo} onClick={downloadLessonAudio}>
              Download MP3
            </button>
          </div>
          {listenErr && <p className="err">{listenErr}</p>}
          {speechInfo && (
            <p className="hint" style={{ marginTop: '0.75rem' }}>
              Engine: <strong>{speechInfo.engine === 'openai_tts' ? 'OpenAI TTS' : 'edge-tts'}</strong> · Characters
              narrated: {speechInfo.characters_used}
              {speechInfo.translation_applied ? (
                <>
                  {' '}
                  · <strong>Translated</strong> to match output language before speech
                </>
              ) : null}
              {speechInfo.truncated ? ' (audio source was truncated for one request; shorten chapter or split later).' : ''}
            </p>
          )}
          {audioUrl && (
            <div className="audio-player-wrap">
              <audio className="lesson-audio" src={audioUrl} controls playsInline>
                Your browser does not support audio.
              </audio>
            </div>
          )}
        </section>
      )}
    </div>
  )
}

export default App
