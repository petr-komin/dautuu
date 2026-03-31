import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useForm } from 'react-hook-form'
import { z } from 'zod'
import { zodResolver } from '@hookform/resolvers/zod'
import toast from 'react-hot-toast'

import { login } from '../api/auth'
import { useAuthStore } from '../store/authStore'
import { Input } from '../components/ui/Input'
import { Button } from '../components/ui/Button'
import { Card, CardContent } from '../components/ui/Card'

const schema = z.object({
  email: z.string().email('Neplatný email'),
  password: z.string().min(6, 'Heslo musí mít alespoň 6 znaků'),
})

type FormData = z.infer<typeof schema>

export function LoginPage() {
  const [loading, setLoading] = useState(false)
  const setToken = useAuthStore((s) => s.setToken)
  const navigate = useNavigate()

  const {
    register: reg,
    handleSubmit,
    formState: { errors },
  } = useForm<FormData>({ resolver: zodResolver(schema) })

  async function onSubmit(data: FormData) {
    setLoading(true)
    try {
      const res = await login({ username: data.email, password: data.password })
      setToken(res.access_token)
      toast.success('Přihlášení úspěšné')
      navigate('/chat')
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        'Nesprávný email nebo heslo'
      toast.error(msg)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-full flex items-center justify-center p-4 bg-[var(--bg)] relative overflow-hidden">

      {/* Stegosaur background decoration */}
      <img
        src="/60475ea1-d1de-4ba2-a849-66c356d47e4e.jpg"
        alt=""
        aria-hidden="true"
        className="absolute inset-0 w-full h-full object-cover pointer-events-none select-none"
        style={{ opacity: 0.12, objectPosition: '50% 70%' }}
      />

      <div className="w-full max-w-sm relative z-10">
        {/* Logo */}
        <div className="flex flex-col items-center gap-3 mb-8">
          <div className="text-center">
            <h1 className="text-2xl font-semibold text-[var(--text)]">dautuu</h1>
            <p className="text-sm text-[var(--text-muted)] mt-1">Osobní AI asistent s pamětí</p>
          </div>
        </div>

        <Card>
          <CardContent>
            <form onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-4">
              <Input
                label="Email"
                type="email"
                placeholder="vas@email.cz"
                autoComplete="email"
                error={errors.email?.message}
                {...reg('email')}
              />
              <Input
                label="Heslo"
                type="password"
                placeholder="••••••••"
                autoComplete="current-password"
                error={errors.password?.message}
                {...reg('password')}
              />

              <Button type="submit" loading={loading} className="mt-2 w-full">
                Přihlásit se
              </Button>
            </form>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
