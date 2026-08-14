const apiBaseUrl = "http://127.0.0.1:8000";
const generateEmailEndpoint = `${apiBaseUrl}/api/ai/generate-email`;
const sendEmailEndpoint = `${apiBaseUrl}/api/gmail/send`;

const chatForm = document.getElementById("chatForm");
const instructionInput = document.getElementById("instruction");
const chatMessages = document.getElementById("chatMessages");
const generateButton = document.getElementById("generateButton");
const clearChatButton = document.getElementById("clearChat");
const textMessageTemplate = document.getElementById("textMessageTemplate");
const draftMessageTemplate = document.getElementById("draftMessageTemplate");
const apiBaseLabel = document.getElementById("apiBaseLabel");
const promptChips = document.querySelectorAll(".prompt-chip");
let conversationHistory = [];

apiBaseLabel.textContent = apiBaseUrl;

function appendMessage(role, text, author) {
  const fragment = textMessageTemplate.content.cloneNode(true);
  const message = fragment.querySelector(".message");
  const authorLabel = fragment.querySelector(".message-author");
  const bubble = fragment.querySelector(".bubble");

  message.classList.add(role);
  authorLabel.textContent =
    author ?? (role === "user" ? "You" : "Email Assistant");
  bubble.textContent = text;
  chatMessages.appendChild(fragment);
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

function setLoadingState(isLoading) {
  generateButton.disabled = isLoading;
  generateButton.textContent = isLoading ? "Generating..." : "Generate Email";
}

async function generateEmail(instruction) {
  const response = await fetch(generateEmailEndpoint, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      instruction,
      messages: conversationHistory,
    }),
  });

  if (!response.ok) {
    throw new Error(`Request failed with status ${response.status}`);
  }

  return response.json();
}

async function sendEmail(draft) {
  const response = await fetch(sendEmailEndpoint, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(draft),
  });

  const data = await response.json();

  if (!response.ok) {
    throw new Error(data.detail ?? `Request failed with status ${response.status}`);
  }

  return data;
}

function readFileAsBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();

    reader.onload = () => {
      const result = typeof reader.result === "string" ? reader.result : "";
      const [, base64Data = ""] = result.split(",", 2);
      resolve(base64Data);
    };

    reader.onerror = () => {
      reject(new Error("Unable to read the selected file."));
    };

    reader.readAsDataURL(file);
  });
}

function setDraftReadonly(fields, isReadonly) {
  fields.forEach((field) => {
    field.readOnly = isReadonly;
  });
}

function buildDraftSummary(draft) {
  const recipient = draft.to?.trim() || "no recipient yet";
  const subject = draft.subject?.trim() || "no subject yet";

  return `I drafted an email to ${recipient} with the subject "${subject}". You can edit any part before sending.`;
}

function buildDraftContextMessage(draft) {
  return [
    "Current draft details:",
    `To: ${draft.to ?? ""}`,
    `Subject: ${draft.subject ?? ""}`,
    "Body:",
    draft.body ?? "",
  ].join("\n");
}

function appendDraftMessage(draft) {
  appendMessage("assistant", buildDraftSummary(draft));
  conversationHistory.push({
    role: "assistant",
    content: buildDraftContextMessage(draft),
  });

  const fragment = draftMessageTemplate.content.cloneNode(true);
  const status = fragment.querySelector('[data-role="draft-status"]');
  const toInput = fragment.querySelector('[data-field="to"]');
  const subjectInput = fragment.querySelector('[data-field="subject"]');
  const bodyInput = fragment.querySelector('[data-field="body"]');
  const attachmentInput = fragment.querySelector('[data-field="attachment"]');
  const attachmentNote = fragment.querySelector('[data-role="attachment-note"]');
  const editButton = fragment.querySelector('[data-action="edit"]');
  const saveButton = fragment.querySelector('[data-action="save"]');
  const sendButton = fragment.querySelector('[data-action="send"]');
  const fields = [toInput, subjectInput, bodyInput];

  toInput.value = draft.to ?? "";
  subjectInput.value = draft.subject ?? "";
  bodyInput.value = draft.body ?? "";

  attachmentInput.addEventListener("change", () => {
    const selectedFile = attachmentInput.files?.[0];
    attachmentNote.textContent = selectedFile
      ? `Attached: ${selectedFile.name}`
      : "No resume attached yet.";
  });

  editButton.addEventListener("click", () => {
    setDraftReadonly(fields, false);
    status.textContent = "Editing draft";
    editButton.hidden = true;
    saveButton.hidden = false;
    appendMessage("assistant", "You can update the recipient, subject, or body, then save when you're ready.");
    toInput.focus();
  });

  saveButton.addEventListener("click", () => {
    setDraftReadonly(fields, true);
    status.textContent = "Draft updated";
    editButton.hidden = false;
    saveButton.hidden = true;
    appendMessage("assistant", "Draft saved. If it looks good, go ahead and send it.");
  });

  sendButton.addEventListener("click", async () => {
    const selectedFile = attachmentInput.files?.[0];
    const payload = {
      to: toInput.value.trim(),
      subject: subjectInput.value.trim(),
      body: bodyInput.value.trim(),
    };

    sendButton.disabled = true;
    editButton.disabled = true;
    saveButton.disabled = true;
    status.textContent = "Sending...";

    try {
      if (selectedFile) {
        payload.attachment = {
          filename: selectedFile.name,
          content_type: selectedFile.type || "application/octet-stream",
          data: await readFileAsBase64(selectedFile),
        };
      }

      const result = await sendEmail(payload);
      status.textContent = `Sent successfully (${result.message_id})`;
      setDraftReadonly(fields, true);
      editButton.hidden = false;
      saveButton.hidden = true;
      appendMessage(
        "assistant",
        selectedFile
          ? `Your email and resume have been sent successfully. Gmail message id: ${result.message_id}.`
          : `Your email has been sent successfully. Gmail message id: ${result.message_id}.`
      );
    } catch (error) {
      status.textContent = "Send failed";
      appendMessage("assistant", `Email send failed: ${error.message}`);
    } finally {
      sendButton.disabled = false;
      editButton.disabled = false;
      saveButton.disabled = false;
    }
  });

  chatMessages.appendChild(fragment);
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

chatForm.addEventListener("submit", async (event) => {
  event.preventDefault();

  const instruction = instructionInput.value.trim();
  if (!instruction) {
    return;
  }

  appendMessage("user", instruction);
  conversationHistory.push({
    role: "user",
    content: instruction,
  });
  instructionInput.value = "";
  setLoadingState(true);
  appendMessage("assistant", "Working on that draft now...");

  try {
    const data = await generateEmail(instruction);
    appendDraftMessage(data);
  } catch (error) {
    appendMessage(
      "assistant",
      `I couldn't reach the generate email endpoint. ${error.message}`
    );
  } finally {
    setLoadingState(false);
    instructionInput.focus();
  }
});

promptChips.forEach((chip) => {
  chip.addEventListener("click", () => {
    instructionInput.value = chip.dataset.prompt ?? "";
    instructionInput.focus();
  });
});

clearChatButton.addEventListener("click", () => {
  conversationHistory = [];
  chatMessages.innerHTML = `
    <article class="message assistant">
      <div class="message-stack">
        <p class="message-author">Email Assistant</p>
        <div class="bubble">
          I can help you draft and send emails. Tell me who it's for and what
          tone you want, and I'll put together a draft you can edit.
        </div>
      </div>
    </article>
  `;
  instructionInput.focus();
});
