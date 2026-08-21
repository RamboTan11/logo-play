/* eslint-disable @typescript-eslint/no-unused-vars */

import type {
  BatchPolicyDataDto,
  BatchPolicyPayloadDto,
  BatchPolicyVersionDto,
  BatchPromptTemplateDto,
  CreateModelConnectionRequest,
  ModelConnectionDto,
  PolicyDraftSavedDto,
  PolicyPublishedDto,
  ReferenceImageAssetDto,
  GenerationStyleCatalogDto,
  SingleImageEditPolicyDataDto,
  SingleImageEditPolicyPayloadDto,
  SingleImageEditPolicyVersionDto,
  TestModelConnectionData,
  UpdateModelConnectionRequest,
} from '../types/modelStrategy'

export class ModelStrategyMockError extends Error {
  validationErrors: [] = []
}

function unavailable<T>(): Promise<T> {
  return Promise.reject(new Error('模型策略接口尚未接入'))
}

export function getModelConnectionsMock(): Promise<ModelConnectionDto[]> {
  return unavailable()
}

export function createModelConnectionMock(_: CreateModelConnectionRequest): Promise<ModelConnectionDto> {
  return unavailable()
}

export function updateModelConnectionMock(
  _: string,
  __: UpdateModelConnectionRequest,
): Promise<ModelConnectionDto> {
  return unavailable()
}

export function deleteModelConnectionMock(_: string): Promise<void> {
  return unavailable()
}

export function testModelConnectionMock(_: string): Promise<TestModelConnectionData> {
  return unavailable()
}

export function getReferenceImageAssetsMock(_: string[] = []): Promise<ReferenceImageAssetDto[]> {
  return unavailable()
}

export function uploadReferenceImageMock(_: File): Promise<ReferenceImageAssetDto> {
  return unavailable()
}

export function getReferenceImageContentMock(_: string): Promise<Blob> {
  return unavailable()
}

export function uploadShowcaseImageMock(_: File): Promise<ReferenceImageAssetDto> {
  return unavailable()
}

export function getGenerationStyleCatalogMock(): Promise<GenerationStyleCatalogDto> {
  return unavailable()
}

export function getGenerationStyleShowcaseContentMock(_: string, __: string): Promise<Blob> {
  return unavailable()
}

export function getBatchPolicyMock(): Promise<BatchPolicyDataDto> {
  return unavailable()
}

export function getBatchPolicyVersionsMock(): Promise<BatchPolicyVersionDto[]> {
  return unavailable()
}

export function saveBatchPolicyDraftMock(_: BatchPolicyPayloadDto): Promise<PolicyDraftSavedDto> {
  return unavailable()
}

export function publishBatchPolicyMock(_: BatchPolicyPayloadDto | undefined): Promise<PolicyPublishedDto> {
  return unavailable()
}

export function getSingleEditPolicyMock(): Promise<SingleImageEditPolicyDataDto> {
  return unavailable()
}

export function getSingleEditPolicyVersionsMock(): Promise<SingleImageEditPolicyVersionDto[]> {
  return unavailable()
}

export function publishSingleEditPolicyMock(
  _: SingleImageEditPolicyPayloadDto,
): Promise<PolicyPublishedDto> {
  return unavailable()
}

export function isCompleteBatchTemplate(_: BatchPromptTemplateDto): boolean {
  return false
}

export function normalizeBatchGenerationGates(policy: BatchPolicyPayloadDto): BatchPolicyPayloadDto {
  return policy
}
