/**
 * API types, generated from the FastAPI (Pydantic) schemas — never edit by hand.
 * Regenerate with `make gen-api` after changing the backend schemas.
 */
import type { components } from "./schema";

type Schemas = components["schemas"];

export type ActivityEvent = Schemas["ActivityEvent"];
export type HealthResponse = Schemas["HealthResponse"];
export type JobLogPage = Schemas["JobLogPage"];
export type JobRead = Schemas["JobRead"];
export type JobStatus = Schemas["JobSummary"]["status"];
export type JobSummary = Schemas["JobSummary"];
export type OverviewResponse = Schemas["OverviewResponse"];
export type Role = Schemas["Role"];
export type TokenResponse = Schemas["TokenResponse"];
export type GoogleConfig = Schemas["GoogleConfig"];
export type UserRead = Schemas["UserRead"];
export type GrantableRole = NonNullable<Schemas["UserUpdate"]["role"]>;
export type SignInRead = Schemas["SignInRead"];
export type AdminActivity = Schemas["AdminActivity"];
export type Limits = Schemas["Limits"];
export type Requests = Schemas["Requests"];
export type WaitingUpload = Schemas["WaitingUpload"];
export type HeldVideo = Schemas["HeldVideo"];

// Phase 1: ingestion and catalog
export type DatasetSummary = Schemas["DatasetSummary"];
export type DeviceSummary = Schemas["DeviceSummary"];
export type OperatorRead = Schemas["OperatorRead"];
export type Ref = Schemas["Ref"];
export type SessionDetail = Schemas["SessionDetail"];
export type SessionSummary = Schemas["SessionSummary"];
export type UploadDetail = Schemas["UploadDetail"];
export type UploadRead = Schemas["UploadRead"];
export type UploadStatus = Schemas["UploadStatus"];
export type VideoDetail = Schemas["VideoDetail"];
export type VideoStatus = Schemas["VideoStatus"];
export type VideoSummary = Schemas["VideoSummary"];

// Phase 2: inspector and manual annotation
export type AdjacentEvent = Schemas["AdjacentEvent"];
export type AnnotationCategory = Schemas["AnnotationCategory"];
export type AnnotationCreate = Schemas["AnnotationCreate"];
export type AnnotationHistory = Schemas["AnnotationHistory"];
export type AnnotationRead = Schemas["AnnotationRead"];
export type AnnotationType = Schemas["AnnotationType"];
export type AnnotationUpdate = Schemas["AnnotationUpdate"];
export type AssignableUser = Schemas["AssignableUser"];
export type AssignmentRead = Schemas["AssignmentRead"];
export type AssignmentStatus = Schemas["AssignmentStatus"];
export type FrameIndex = Schemas["FrameIndex"];
export type JobRef = Schemas["JobRef"];
export type LabelCount = Schemas["LabelCount"];
export type RevisionRead = Schemas["RevisionRead"];
export type TimelineRead = Schemas["TimelineRead"];
export type TimelineTrackData = Schemas["TimelineTrack"];

// Phase 3: hand and finger tracking
export type AdapterInfo = Schemas["AdapterInfo"];
export type CvRunDetail = Schemas["CvRunDetail"];
export type CvRunStatus = Schemas["CvRunStatus"];
export type CvRunSummary = Schemas["CvRunSummary"];
export type FrameHands = Schemas["FrameHands"];
export type HandInFrame = Schemas["HandInFrame"];
export type HandTrackRead = Schemas["HandTrackRead"];
export type RunFrames = Schemas["RunFrames"];
export type RunSeries = Schemas["RunSeries"];
export type SeriesPoint = Schemas["SeriesPoint"];

// Phase 4: object detection and movement classification
export type CvRunKind = Schemas["CvRunKind"];
export type ClassRef = Schemas["ClassRef"];
export type EventEvidenceFrames = Schemas["EventEvidenceFrames"];
export type EvidenceFrame = Schemas["EvidenceFrame"];
export type FrameObjects = Schemas["FrameObjects"];
export type InteractionGraph = Schemas["InteractionGraph"];
export type MovementClassRead = Schemas["MovementClassRead"];
export type MovementEventDetail = Schemas["MovementEventDetail"];
export type MovementEventStatus = Schemas["MovementEventStatus"];
export type MovementEventSummary = Schemas["MovementEventSummary"];
export type ObjectInFrame = Schemas["ObjectInFrame"];
export type ObjectTrackRead = Schemas["ObjectTrackRead"];
export type RunObjects = Schemas["RunObjects"];

// Phase 5: review and active learning
export type AutoAnnotateResult = Schemas["AutoAnnotateResult"];
export type BulkPreview = Schemas["BulkPreview"];
export type CorrectionResult = Schemas["CorrectionResult"];
export type EventHistory = Schemas["EventHistory"];
export type ModelVersionRead = Schemas["ModelVersionRead"];
export type QueuePage = Schemas["QueuePage"];
export type ReviewBatchRead = Schemas["ReviewBatchRead"];
export type ReviewFilters = Schemas["ReviewFilters"];
export type ReviewGroup = Schemas["ReviewGroup"];
export type ReviewItem = Schemas["ReviewItem"];
export type ReviewMethod = Schemas["ReviewMethod"];
export type ReviewMetrics = Schemas["ReviewMetrics"];
export type ReviewRuleRead = Schemas["ReviewRuleRead"];
export type ReviewSummary = Schemas["ReviewSummary"];

// Phase 6: datasets, versions, exports, lineage
export type CheckRead = Schemas["CheckRead"];
export type DatasetDetail = Schemas["DatasetDetail"];
export type DatasetFacets = Schemas["DatasetFacets"];
export type DatasetFilters = Schemas["DatasetFilters"];
export type DatasetPreview = Schemas["DatasetPreview"];
export type DatasetSpec = Schemas["DatasetSpec"];
export type ExportDownload = Schemas["ExportDownload"];
export type ExportFormat = Schemas["ExportFormat"];
export type ExportRead = Schemas["ExportRead"];
export type LineageGraph = Schemas["LineageGraph"];
export type LineageNode = Schemas["LineageNode"];
export type SampleRead = Schemas["SampleRead"];
export type SplitSpec = Schemas["SplitSpec"];
export type VersionCounts = Schemas["VersionCounts"];
export type VersionDetail = Schemas["VersionDetail"];
export type VersionSummary = Schemas["VersionSummary"];

// Phase 7: pipelines, runs, schedules, quality checks, annotated videos
export type AnnotatedVideoRead = Schemas["AnnotatedVideoRead"];
export type AttemptRead = Schemas["AttemptRead"];
export type CronPreview = Schemas["CronPreview"];
export type GraphCheck = Schemas["GraphCheck"];
export type NodeProgress = Schemas["NodeProgress"];
export type PipelineDetail = Schemas["PipelineDetail"];
export type PipelineRunStatus = Schemas["PipelineRunStatus"];
export type PipelineSummary = Schemas["PipelineSummary"];
export type QualityCheckRead = Schemas["QualityCheckRead"];
export type RunDetail = Schemas["RunDetail"];
export type RunLogLine = Schemas["RunLogLine"];
export type RunLogPage = Schemas["RunLogPage"];
export type RunSummary = Schemas["RunSummary"];
export type ScheduleRead = Schemas["ScheduleRead"];
export type StepRead = Schemas["StepRead"];
export type StepStatus = Schemas["StepStatus"];
export type StepTypeRead = Schemas["StepTypeRead"];
export type TemplateRead = Schemas["TemplateRead"];
export type VideoQuality = Schemas["VideoQuality"];

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}
