import { renderToStaticMarkup } from "react-dom/server";
import { ChatAppResponse, getCitationFilePath } from "../../api";

type HtmlParsedAnswer = {
    answerHtml: string;
    citations: string[];
    citationUrls: string[];
};

// Function to validate citation format and check if dataPoint starts with possible citation
function isCitationValid(contextDataPoints: any, citationCandidate: string): boolean {
    const regex = /.+\.\w{1,}(?:#\S*)?$/;
    if (!regex.test(citationCandidate)) {
        return false;
    }

    // Check if contextDataPoints is an object with a text property that is an array
    let dataPointsArray: string[];
    if (Array.isArray(contextDataPoints)) {
        dataPointsArray = contextDataPoints;
    } else if (contextDataPoints && Array.isArray(contextDataPoints.text)) {
        dataPointsArray = contextDataPoints.text;
    } else {
        return false;
    }

    const isValidCitation = dataPointsArray.some(dataPoint => {
        return dataPoint.startsWith(citationCandidate);
    });

    return isValidCitation;
}

function findCitationIndexInDataPoints(contextDataPoints: any, citationCandidate: string): number {
    let dataPointsArray: string[];
    // Determine the correct array of source documents based on common structures
    if (Array.isArray(contextDataPoints)) {
        dataPointsArray = contextDataPoints;
    } else if (contextDataPoints && Array.isArray(contextDataPoints.text)) {
        dataPointsArray = contextDataPoints.text;
    } else if (contextDataPoints && Array.isArray(contextDataPoints.sources)) {
        dataPointsArray = contextDataPoints.sources;
    } else {
        console.error("Could not determine data points array structure:", contextDataPoints);
        return -1; // Cannot determine data points array
    }

    // Find the index where the data point starts with the citation text
    return dataPointsArray.findIndex(dataPoint => typeof dataPoint === "string" && dataPoint.startsWith(citationCandidate));
}

export function parseAnswerToHtml(answer: ChatAppResponse, isStreaming: boolean, onCitationClicked: (citationFilePath: string) => void): HtmlParsedAnswer {
    const sourceUrls: string[] = answer.context.data_addon?.sourceurl || [];
    const contextDataPoints = answer.context.data_points;

    // This array will store pairs of { identifier, url } for unique citations found IN THE ANSWER TEXT
    const foundCitationsInText: { identifier: string; url: string }[] = [];

    // Trim any whitespace from the end of the answer after removing follow-up questions
    let parsedAnswer = answer.message.content.trim();

    // Omit a citation that is still being typed during streaming
    if (isStreaming) {
        let lastIndex = parsedAnswer.length;
        for (let i = parsedAnswer.length - 1; i >= 0; i--) {
            if (parsedAnswer[i] === "]") {
                break;
            } else if (parsedAnswer[i] === "[") {
                lastIndex = i;
                break;
            }
        }
        const truncatedAnswer = parsedAnswer.substring(0, lastIndex);
        parsedAnswer = truncatedAnswer;
    }

    const parts = parsedAnswer.split(/\[([^\]]+)\]/g);

    // Reconstruct the answer HTML, identify citations, and collect their URLs
    const fragments: string[] = parts.map((part, index) => {
        if (index % 2 === 0) {
            // Regular text part
            return part;
        } else {
            // Potential citation identifier (e.g., "file1.pdf#page=1")
            const potentialCitationIdentifier = part;

            // Find the index in the original data points list
            const dataPointIndex = findCitationIndexInDataPoints(contextDataPoints, potentialCitationIdentifier);

            // Basic validation
            const looksLikeCitation = /.+\.\w{1,}(?:#\S*)?$/.test(potentialCitationIdentifier);

            if (dataPointIndex === -1 || !looksLikeCitation) {
                // Not a valid citation found in context or doesn't look right, return as text
                return `[${potentialCitationIdentifier}]`;
            }

            // Get the corresponding URL using the index
            const citationUrl = sourceUrls[dataPointIndex];
            // We don't strictly need the URL here for rendering the main text,
            // but we DO need to know if this citation is valid and track it.

            // Manage the list of found citations (unique identifiers and their URLs)
            let citationDisplayIndex: number;
            const existingCitation = foundCitationsInText.find(c => c.identifier === potentialCitationIdentifier);

            if (existingCitation) {
                citationDisplayIndex = foundCitationsInText.indexOf(existingCitation) + 1;
            } else {
                // Only add if URL exists for safety, though ideally backend ensures consistency
                if (citationUrl !== undefined) {
                    foundCitationsInText.push({ identifier: potentialCitationIdentifier, url: citationUrl });
                } else {
                    console.warn(`URL missing for citation identifier: ${potentialCitationIdentifier} at index ${dataPointIndex}`);
                    // Decide how to handle missing URL - maybe still add identifier? Or skip?
                    // For now, let's add the identifier but maybe log the missing URL
                    foundCitationsInText.push({ identifier: potentialCitationIdentifier, url: "" }); // Add with empty URL if missing
                }
                citationDisplayIndex = foundCitationsInText.length;
            }

            // Render the citation number as a superscript in the main text
            // We are NOT putting the URL here anymore
            return renderToStaticMarkup(
                <sup className="citationNumber" title={potentialCitationIdentifier}>
                    {citationDisplayIndex}
                </sup>
            );
        }
    });

    return {
        answerHtml: fragments.join(""), // The answer text with <sup> tags
        citations: foundCitationsInText.map(c => c.identifier), // List of unique identifiers found in the text
        citationUrls: foundCitationsInText.map(c => c.url) // Corresponding URLs in the same order
    };
}
