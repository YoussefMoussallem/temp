import UserMessage from "./UserMessage";
import AssistantMessage from "./AssistantMessage";
import CommandResult from "./CommandResult";
import CompactBoundary from "./CompactBoundary";

export default function Message({ message }) {
  switch (message.role) {
    case "user":
      return (
        <UserMessage
          content={message.content}
          commandUuid={message.commandUuid}
          commandState={message.commandState}
          raw={message.raw}
        />
      );
    case "system":
      return (
        <CommandResult
          content={message.content}
          command={message.command}
          data={message.data}
        />
      );
    case "assistant":
      return <AssistantMessage content={message.content} meta={message.meta} />;
    case "compact-boundary":
      return <CompactBoundary boundary={message.boundary} />;
    default:
      return null;
  }
}
