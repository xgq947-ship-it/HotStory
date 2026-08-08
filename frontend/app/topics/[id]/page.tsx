import { ResearchWorkspace } from "@/components/ResearchWorkspace";

export default async function TopicPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <ResearchWorkspace topicId={id} />;
}

