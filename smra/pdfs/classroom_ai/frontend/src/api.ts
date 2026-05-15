const API = '/api/v1'

export type VisualBrief = {
  title: string
  description: string
  kind: string
  suggested_format: string
  mermaid_diagram?: string | null // Optional: subtopic diagram
  src?: string | null // Optional: image URL or base64
}

export type ExplainResponse = {
  explanation_markdown: string
  simple_examples: string[]
  visual_briefs: VisualBrief[]
  suggested_followup_topics: string[]
  video_lesson_prompt: string | null
  mermaid_diagram: string | null
  /** Legend / how to read the diagram (same language as lesson). */
  diagram_caption?: string | null
  output_language_used: OutputLanguageCode | null
  pdf_extraction_notes?: string | null
  /** Raw PDF extraction echoed for quiz/slides when using PDF mode */
  source_text_used_for_context?: string | null
}

export type OutputLanguageCode = 'english' | 'hindi' | 'roman_hindi'
export type ModelStack = 'openai' | 'opensource'

/** Video tab only: Pexels = stock footage; lesson_overview = narrated explainer from your text (Notebook LM–style). */
export type VideoJobStack = ModelStack | 'pexels' | 'lesson_overview'

export type LessonOverviewStyle = 'explainer' | 'brief'

export const OUTPUT_LANGUAGE_LABELS: Record<OutputLanguageCode, string> = {
  english: 'English',
  hindi: 'Hindi (देवनागरी)',
  roman_hindi: 'Roman Hindi',
}


export type QuizQuestion = {
  id: string
  question: string
  options: string[]
  correct_option_index: number
  correct_explanation: string
  wrong_explanation: string
  option_explanations?: string[] | null
}

export type QuizResponse = {
  topic: string
  output_language_used: OutputLanguageCode
  questions: QuizQuestion[]
}

export type VideoJob = {
  id: string
  status: string
  progress: number | null
  model: string | null
  seconds: string | null
  size: string | null
  error: { code?: string | null; message?: string | null } | null
}

async function readError(res: Response): Promise<string> {
  try {
    const j = await res.json()
    if (typeof j.detail === 'string') return j.detail
    if (Array.isArray(j.detail)) return JSON.stringify(j.detail)
    return JSON.stringify(j)
  } catch {
    return res.statusText
  }
}

export async function explainFromText(
  chapterText: string,
  outputLanguage: OutputLanguageCode,
  topicHint: string,
  stack: ModelStack,
): Promise<ExplainResponse> {
  const fd = new FormData()
  fd.set('output_language', outputLanguage)
  fd.set('chapter_text', chapterText)
  if (topicHint.trim()) fd.set('topic_hint', topicHint.trim())
  fd.set('stack', stack)

  const res = await fetch(`${API}/explain/text-form`, { method: 'POST', body: fd })
  if (!res.ok) throw new Error(await readError(res))
  return res.json()
}

export async function explainFromImages(
  files: File[],
  outputLanguage: OutputLanguageCode,
  topicHint: string,
  stack: ModelStack,
): Promise<ExplainResponse> {
  const fd = new FormData()
  fd.set('output_language', outputLanguage)
  files.forEach((f) => fd.append('files', f))
  if (topicHint.trim()) fd.set('topic_hint', topicHint.trim())
  fd.set('stack', stack)

  const res = await fetch(`${API}/explain/images`, { method: 'POST', body: fd })
  if (!res.ok) throw new Error(await readError(res))
  return res.json()
}

export async function explainFromPdf(
  file: File,
  outputLanguage: OutputLanguageCode,
  topicHint: string,
  stack: ModelStack,
  ocrPages: boolean,
  ocrImages: boolean,
): Promise<ExplainResponse> {
  const fd = new FormData()
  fd.set('file', file)
  fd.set('output_language', outputLanguage)
  if (topicHint.trim()) fd.set('topic_hint', topicHint.trim())
  fd.set('stack', stack)
  fd.set('ocr_pages', ocrPages ? 'true' : 'false')
  fd.set('ocr_images', ocrImages ? 'true' : 'false')

  const res = await fetch(`${API}/explain/pdf`, { method: 'POST', body: fd })
  if (!res.ok) throw new Error(await readError(res))
  return res.json()
}

export type OpensourceAnimationPreset = 'classic' | 'motion_plus'

export async function createVideoJob(body: {
  prompt: string
  seconds: '4' | '8' | '12'
  model: string
  size: string | null
  input_reference_image_url: string | null
  /** Above 12: server runs create(12s) + extend segments (~30 → ~32s total). */
  chain_target_seconds?: number | null
  stack: VideoJobStack
  /** Open-source local MP4 only. */
  opensource_animation?: OpensourceAnimationPreset | null
  /** lesson_overview: full text to turn into a narrated explainer video */
  lesson_source_text?: string | null
  lesson_overview_style?: LessonOverviewStyle
  output_language?: OutputLanguageCode
  lesson_use_pexels_background?: boolean
  /** Same as Learn Model stack — LLM + TTS for lesson overview */
  lesson_llm_stack?: ModelStack
}): Promise<VideoJob> {
  const res = await fetch(`${API}/video/jobs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(await readError(res))
  return res.json()
}

export async function getVideoJob(id: string): Promise<VideoJob> {
  const res = await fetch(`${API}/video/jobs/${encodeURIComponent(id)}`)
  if (!res.ok) throw new Error(await readError(res))
  return res.json()
}

export async function fetchVideoBlob(id: string): Promise<Blob> {
  const res = await fetch(`${API}/video/jobs/${encodeURIComponent(id)}/file`)
  if (!res.ok) throw new Error(await readError(res))
  return res.blob()
}

export function fileToDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader()
    r.onload = () => resolve(r.result as string)
    r.onerror = () => reject(r.error)
    r.readAsDataURL(file)
  })
}

export async function generateIllustration(
  prompt: string,
  stack: ModelStack,
  source: 'ai' | 'pexels' = 'ai',
): Promise<string> {
  const res = await fetch(`${API}/illustration`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ prompt, stack, source }),
  })
  if (!res.ok) throw new Error(await readError(res))
  const j = (await res.json()) as { image_base64: string; mime_type: string }
  return `data:${j.mime_type};base64,${j.image_base64}`
}


export async function generateQuiz(body: {
  topic: string
  context_text: string | null
  output_language: OutputLanguageCode
  stack: ModelStack
  question_count: number
  difficulty: 'remedial' | 'standard' | 'advanced'
}): Promise<QuizResponse> {
  const res = await fetch(`${API}/quiz/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(await readError(res))
  return res.json()
}

export type SlideItem = {
  title: string
  bullets: string[]
  speaker_notes?: string | null
  image_query?: string | null
  photo_attribution?: string | null
}

export type SlideDeckResponse = {
  deck_id: string
  deck_title: string
  filename: string
  slides: SlideItem[]
}

export async function generateSlideDeck(body: {
  topic: string
  context_text: string | null
  output_language: OutputLanguageCode
  stack: ModelStack
  slide_count: number
}): Promise<SlideDeckResponse> {
  const res = await fetch(`${API}/slides/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(await readError(res))
  return res.json()
}

export async function fetchSlideDeckBlob(deckId: string): Promise<Blob> {
  const res = await fetch(`${API}/slides/${encodeURIComponent(deckId)}/file`)
  if (!res.ok) throw new Error(await readError(res))
  return res.blob()
}

export type SpeechResponse = {
  audio_id: string
  filename: string
  mime_type: string
  engine: 'openai_tts' | 'edge_tts'
  truncated: boolean
  characters_used: number
  translation_applied: boolean
}

export async function generateSpeech(body: {
  context_text: string
  output_language: OutputLanguageCode
  stack: ModelStack
  openai_voice?: string
  openai_tts_model?: string
  edge_voice?: string | null
}): Promise<SpeechResponse> {
  const payload: Record<string, unknown> = {
    context_text: body.context_text,
    output_language: body.output_language,
    stack: body.stack,
    openai_voice: body.openai_voice ?? 'nova',
    openai_tts_model: body.openai_tts_model ?? 'tts-1',
  }
  if (body.edge_voice && body.edge_voice.trim()) {
    payload.edge_voice = body.edge_voice.trim()
  }
  const res = await fetch(`${API}/audio/speech`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) throw new Error(await readError(res))
  return res.json()
}

export async function fetchSpeechBlob(audioId: string): Promise<Blob> {
  const res = await fetch(`${API}/audio/${encodeURIComponent(audioId)}/file`)
  if (!res.ok) throw new Error(await readError(res))
  return res.blob()
}

export type FlashcardItem = { front: string; back: string }

export type FlashcardsResponse = {
  topic: string
  output_language_used: OutputLanguageCode
  cards: FlashcardItem[]
}

export async function generateFlashcards(body: {
  topic: string
  context_text: string | null
  output_language: OutputLanguageCode
  stack: ModelStack
  card_count: number
}): Promise<FlashcardsResponse> {
  const res = await fetch(`${API}/flashcards/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(await readError(res))
  return res.json()
}

export type InfographicResponse = {
  image_base64: string
  mime_type: string
  image_prompt_used: string
}

export async function generateInfographic(body: {
  topic: string
  context_text: string | null
  output_language: OutputLanguageCode
  stack: ModelStack
  style?: string
}): Promise<InfographicResponse> {
  const res = await fetch(`${API}/infographic/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(await readError(res))
  return res.json()
}

import axios from 'axios';

export async function fetchRelevantImages(text: string): Promise<string[]> {
  try {
    const response = await axios.post('/api/v1/explain/images', { text });
    return response.data.images; // Assuming the API returns an array of image URLs
  } catch (error) {
    console.error('Error fetching relevant images:', error);
    throw error;
  }
}
