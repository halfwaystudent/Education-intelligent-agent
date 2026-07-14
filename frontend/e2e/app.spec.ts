import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

const LONG_QUESTION = `\u7ed9\u6211\u8bb2\u4e2a\u7b11\u8bdd\u3002\u8fd9\u662f\u4e00\u6bb5\u7528\u4e8e\u9a8c\u8bc1\u957f\u5bf9\u8bdd\u6eda\u52a8\u5e03\u5c40\u7684\u6d4b\u8bd5\u5185\u5bb9\uff0c${'\u6d88\u606f\u5185\u5bb9\u9700\u8981\u5728\u8f83\u7a84\u7684\u804a\u5929\u5361\u7247\u4e2d\u81ea\u52a8\u6362\u884c\u3002'.repeat(8)}`

async function createLongConversation(request: APIRequestContext, rounds = 10): Promise<string> {
  let sessionId: string | null = null
  for (let index = 0; index < rounds; index += 1) {
    const response = await request.post('/api/chat', {
      data: {
        question: `${index + 1}. ${LONG_QUESTION}`,
        subject: '\u6570\u5b66',
        collection_name: 'math_collection',
        session_id: sessionId,
      },
    })
    expect(response.ok()).toBeTruthy()
    const payload = await response.json() as { session_id: string }
    sessionId = payload.session_id
  }
  if (!sessionId) throw new Error('Failed to create the long-conversation test session')
  return sessionId
}

async function expectScrollableMessagesAndVisibleComposer(page: Page, expectedMessageCount: number): Promise<void> {
  await expect(page.locator('.messages-column .message-row')).toHaveCount(expectedMessageCount)
  const messageMetrics = await page.locator('.message-area').evaluate((element) => ({
    clientHeight: element.clientHeight,
    scrollHeight: element.scrollHeight,
  }))
  expect(messageMetrics.scrollHeight).toBeGreaterThan(messageMetrics.clientHeight)

  const composer = page.locator('.composer-area')
  await expect(composer).toBeVisible()
  const composerBox = await composer.boundingBox()
  const viewport = page.viewportSize()
  expect(composerBox).not.toBeNull()
  expect(viewport).not.toBeNull()
  expect(composerBox!.y).toBeGreaterThanOrEqual(0)
  expect(composerBox!.y + composerBox!.height).toBeLessThanOrEqual(viewport!.height + 1)

  const textarea = page.locator('.composer textarea')
  await textarea.click()
  await expect(textarea).toBeFocused()
}

test('loads the student answer workspace', async ({ page }) => {
  await page.goto('/chat')
  await expect(page.getByRole('heading', { name: '智能答疑' })).toBeVisible()
  await expect(page.getByRole('link', { name: /试卷分析/ })).toBeVisible()
  await expect(page.getByRole('link', { name: /知识库管理/ })).toBeVisible()
})

test('renders a completed streaming answer and persists the session route', async ({ page, request }) => {
  await page.goto('/chat')
  await page.locator('textarea').fill('给我讲个笑话')
  await page.getByRole('button', { name: '发送' }).click()
  await expect(page.getByText('这个问题不属于当前课程知识库答疑范围。', { exact: false })).toBeVisible()
  await expect(page.getByText('超出范围', { exact: true })).toBeVisible()
  await expect(page.getByText('正在思考…', { exact: true })).toHaveCount(0)
  await page.waitForURL(/\/chat\/[a-f0-9]+$/)
  const sessionId = page.url().split('/chat/')[1]
  await request.delete(`/api/chat/sessions/${sessionId}`)
})

for (const viewport of [
  { name: 'desktop', width: 1440, height: 800 },
  { name: 'mobile', width: 390, height: 844 },
]) {
  test(`keeps the composer visible during a long conversation on ${viewport.name}`, async ({ page, request }) => {
    await page.setViewportSize({ width: viewport.width, height: viewport.height })
    const sessionId = await createLongConversation(request)
    try {
      await page.goto(`/chat/${sessionId}`)
      await expectScrollableMessagesAndVisibleComposer(page, 20)
    } finally {
      await request.delete(`/api/chat/sessions/${sessionId}`)
    }
  })
}
