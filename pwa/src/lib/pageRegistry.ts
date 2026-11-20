import { PAGE_REGISTRY_PRIMARY } from './pageRegistryPrimary'
import { PAGE_REGISTRY_SECONDARY } from './pageRegistrySecondary'
import type { PageDef } from './pageRegistryDefs'

export { hasRole, passesFeatureFlag } from './pageRegistryDefs'
export type { PageDef } from './pageRegistryDefs'

export const PAGE_REGISTRY: PageDef[] = [...PAGE_REGISTRY_PRIMARY, ...PAGE_REGISTRY_SECONDARY]
