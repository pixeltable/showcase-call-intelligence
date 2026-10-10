export interface UploadIdentity { fingerprint: string; key: string }
export function uploadIdentity(form: FormData, previous: UploadIdentity | null): Promise<UploadIdentity>;
