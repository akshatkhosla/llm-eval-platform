import { useState, useRef, useEffect, useCallback } from 'react'
import { X, Play, AlertCircle } from 'lucide-react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { createEval } from '../lib/api'
import { cn } from '../lib/utils'

const TEMPLATE = `eval:
  model: gemini/gemini-2.5-flash-lite
  dataset: data/dataset.jsonl
  timeout_seconds: 60
  max_concurrency: 1
  judges:
    - type: llm
      model: gemini/gemini-2.5-flash
      rubric: >
        Rate from 0 to 10 how faithfully and accurately the response
        answers the question. A score of 10 means the answer is
        completely correct and directly addresses the question.
        A score of 0 means the answer is wrong or off-topic.
    - type: contains_keyword
      keyword: python
      case_sensitive: false

providers:
  gemini:
    max_concurrency: 1`

interface Props {
  open: boolean
  onClose: () => void
}

export function NewEvalModal({ open, onClose }: Props) {
  const [yaml, setYaml] = useState(TEMPLATE)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const queryClient = useQueryClient()

  const mutation = useMutation({
    mutationFn: () => createEval(yaml),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['evals'] })
      setYaml(TEMPLATE)
      onClose()
    },
  })

  // Focus textarea when opened
  useEffect(() => {
    if (open) {
      const t = setTimeout(() => textareaRef.current?.focus(), 60)
      return () => clearTimeout(t)
    }
  }, [open])

  // Close on Escape
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    },
    [onClose],
  )
  useEffect(() => {
    if (!open) return
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [open, handleKeyDown])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/50 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden
      />

      {/* Modal card */}
      <div
        role="dialog"
        aria-modal
        aria-label="New Eval Run"
        className="relative z-10 w-full max-w-2xl bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl shadow-2xl shadow-black/30 flex flex-col max-h-[90vh]"
      >
        {/* Header */}
        <div className="flex items-start justify-between px-6 py-5 border-b border-zinc-100 dark:border-zinc-800">
          <div>
            <h2 className="text-base font-semibold text-zinc-900 dark:text-zinc-100">
              New Eval Run
            </h2>
            <p className="text-sm text-zinc-500 dark:text-zinc-400 mt-0.5">
              Paste or edit a YAML config to start an evaluation
            </p>
          </div>
          <button
            onClick={onClose}
            className="text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-100 transition-colors rounded-md p-1 hover:bg-zinc-100 dark:hover:bg-zinc-800 ml-4 flex-shrink-0"
            aria-label="Close"
          >
            <X size={18} />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-auto p-6">
          <label
            htmlFor="yaml-editor"
            className="block text-sm font-medium text-zinc-700 dark:text-zinc-300 mb-2"
          >
            Config YAML
          </label>
          <textarea
            id="yaml-editor"
            ref={textareaRef}
            value={yaml}
            onChange={(e) => setYaml(e.target.value)}
            spellCheck={false}
            className={cn(
              'w-full h-80 rounded-lg font-mono text-sm resize-none outline-none px-4 py-3',
              'bg-zinc-50 dark:bg-zinc-950 text-zinc-800 dark:text-zinc-200',
              'placeholder-zinc-400 dark:placeholder-zinc-600',
              'border transition-all scrollbar-thin',
              'focus:ring-2 focus:ring-blue-500/40 focus:border-blue-500/50',
              mutation.isError
                ? 'border-red-400 dark:border-red-500/60'
                : 'border-zinc-200 dark:border-zinc-700',
            )}
          />

          {mutation.isError && (
            <div className="mt-2.5 flex items-start gap-2 text-sm text-red-600 dark:text-red-400">
              <AlertCircle size={15} className="mt-0.5 flex-shrink-0" />
              <span>{(mutation.error as Error).message}</span>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-zinc-100 dark:border-zinc-800">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm font-medium text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-100 transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={() => mutation.mutate()}
            disabled={mutation.isPending || !yaml.trim()}
            className={cn(
              'inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium',
              'bg-blue-600 hover:bg-blue-500 text-white transition-colors',
              'focus:outline-none focus:ring-2 focus:ring-blue-500/50 focus:ring-offset-2 focus:ring-offset-white dark:focus:ring-offset-zinc-900',
              'disabled:opacity-50 disabled:cursor-not-allowed',
            )}
          >
            {mutation.isPending ? (
              <>
                <span className="h-3.5 w-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                Starting…
              </>
            ) : (
              <>
                <Play size={13} />
                Start Eval
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  )
}
