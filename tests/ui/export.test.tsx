import { cleanup, render, screen } from '@testing-library/react'
import App from '../../src/ui/src/App'
import { describeReal, realClient } from './helpers'

describeReal('download of a table summary as Excel', () => {
  it('offers a Download Excel link pointing at the export endpoint', async () => {
    const client = realClient()
    const object = (await client.targets('SP_CLO')).find((o) => o.object_name === 'CM_PAR_LOAN_TRADES')!
    cleanup()
    window.history.replaceState(null, '', `#/summary/SP_CLO/${object.object_id}`)
    render(<App client={client} />)
    const link = (await screen.findByRole('link', { name: 'Download Excel' })) as HTMLAnchorElement
    expect(link.getAttribute('href')).toMatch(new RegExp(`/targets/${object.object_id}/export\\.xlsx\\?project=SP_CLO$`))
    expect(link.getAttribute('download')).not.toBeNull()
  })
})
